"""CRSBench patch verification scoring strategy.

Verifies agent-submitted patches by:
1. Finding ``.diff`` patch file(s) in ``patch_dir`` via ``sandbox().exec()``
2. Applying the patch to source (``patch -p1``)
3. Rebuilding with AddressSanitizer (``build_script`` or fallback ``make``)
4. Running ALL ground-truth POVs against the patched binary (should NOT crash)
5. Running unit tests (``test.sh``) if present

Score tiers:
- 1.0: Builds + fixes all crashes + passes tests
- 0.5: Builds + fixes all crashes but fails unit tests
- 0.0: Doesn't build, no patch found, or still crashes on any POV
"""

from __future__ import annotations

import logging
import posixpath
import shlex

# Domain loggers use saber.domains.* namespace so they inherit
# saber's logging configuration and flow through inspect_ai's LogHandler.

from inspect_ai.scorer import Score
from inspect_ai.util import sandbox

from saber.config.models import DomainCriteria
from saber.scoring.context import ScoringContext

logger = logging.getLogger("saber.domains.crsbench.scoring.patch_verify")


class CRSBenchPatchVerifyStrategy:
    """Patch verification strategy implementing ``SaberScoringStrategy`` protocol.

    Reads criteria fields from ``DomainCriteria.model_extra``:
      - ``source_dir``: Path to source code in sandbox (default ``/workspace/source``)
      - ``build_script``: Path to build script (optional)
      - ``harness_name``: Name of fuzz harness binary
      - ``harness_path``: Path to harness binary in sandbox
      - ``pov_dir``: Path to POV files directory (default ``/workspace/povs``)
      - ``test_script``: Path to test script (optional)
      - ``patch_dir``: Path where agent places patches (default ``/submit/patches``)
    """

    async def score(
        self,
        ctx: ScoringContext,
        renderer: object,
    ) -> Score:
        """Apply patch, rebuild, run POVs, run tests. Return tiered score."""
        criteria = ctx.scorer.criteria
        if not isinstance(criteria, DomainCriteria):
            return Score(
                value=0.0,
                answer=ctx.submission,
                explanation=f"Expected DomainCriteria, got {type(criteria).__name__}",
            )

        extra = criteria.model_extra or {}
        source_dir = extra.get("source_dir") or "/workspace/source"
        build_script = extra.get("build_script") or ""
        harness_path = extra.get("harness_path") or ""
        pov_dir = extra.get("pov_dir") or "/workspace/povs"
        test_script = extra.get("test_script") or ""
        patch_dir = extra.get("patch_dir") or "/submit/patches"
        max_score: float = ctx.scorer.max_score

        sbx = sandbox()

        # Step 1: Find patch file
        find_result = await sbx.exec(
            ["find", patch_dir, "-name", "*.diff", "-type", "f"],
            timeout=30,
        )
        if find_result.returncode != 0 or not find_result.stdout.strip():
            return Score(
                value=0.0,
                answer=ctx.submission,
                explanation=f"No .diff patch file found in {patch_dir}",
            )

        # Only the first .diff file is used; multiple patches are not supported.
        # The agent should consolidate changes into a single patch file.
        patch_file = find_result.stdout.strip().split("\n")[0]
        logger.info("Found patch: %s", patch_file)

        # Step 2: Apply patch to source
        # Agents may produce patches with varied path formats:
        #   - git style:     --- a/mock-c/mock.c
        #   - diff -u style: --- /workspace/source/mock-c/mock.c.bak
        #   - tmp copy:      --- /tmp/mock.c.old   2026-03-06 ...
        # Normalise the patch so it always uses git-style a/ b/ paths
        # relative to the source directory, then apply with git apply
        # (more reliable context matching) or fall back to GNU patch.
        src_q = shlex.quote(str(source_dir))

        # Inline Python normaliser avoids sed ERE escaping pitfalls.
        # Strips absolute source_dir prefixes, a/ b/ prefixes, backup
        # suffixes (.bak, .orig, .old, .new, ~), timestamps, and re-adds
        # a/ b/.  When the stripped path doesn't exist in source_dir it
        # searches the tree for a matching basename so patches created
        # against /tmp copies still resolve correctly.  Finally, recalculate
        # @@ hunk header line counts since LLMs frequently get them wrong.
        normalise_script = "\n".join([
            "import re, sys, os, pathlib",
            f"src = {str(source_dir)!r}",
            "def resolve(p):",
            "  if os.path.exists(os.path.join(src, p)): return p",
            "  base = os.path.basename(p)",
            "  for root, dirs, files in os.walk(src):",
            "    if base in files:",
            "      return os.path.relpath(os.path.join(root, base), src)",
            "  return p",
            "lines = pathlib.Path(sys.argv[1]).read_text()",
            "out = []",
            "for ln in lines.splitlines():",
            "  m = re.match(r'^(---|\\+\\+\\+)\\s+(.*)', ln)",
            "  if not m:",
            "    out.append(ln + chr(10))",
            "    continue",
            "  raw = m.group(2).replace(src + '/', '').lstrip('/')",
            "  raw = re.sub(r'^[ab]/', '', raw)",
            "  raw = re.sub(r'\\t.*', '', raw)",
            "  raw = re.sub(r'\\.(bak|orig|old|new)(\\s.*|[0-9].*)?$', '', raw)",
            "  raw = raw.rstrip('~')",
            "  raw = resolve(raw)",
            "  prefix = 'a/' if m.group(1) == '---' else 'b/'",
            "  out.append(m.group(1) + ' ' + prefix + raw + chr(10))",
            # --- pass 2: fix hunk-header line counts ---
            "fixed = []",
            "i = 0",
            "while i < len(out):",
            "  hm = re.match(r'^@@ -(\\d+)(?:,\\d+)? \\+(\\d+)(?:,\\d+)? @@(.*)', out[i])",
            "  if not hm:",
            "    fixed.append(out[i])",
            "    i += 1",
            "    continue",
            "  oc = nc = 0",
            "  j = i + 1",
            "  while j < len(out):",
            "    hl = out[j].rstrip(chr(10))",
            "    if hl.startswith('@@') or hl.startswith('diff ') or re.match(r'^(---|\\+\\+\\+) [ab]/', hl):",
            "      break",
            "    if hl.startswith('+'):",
            "      nc += 1",
            "    elif hl.startswith('-'):",
            "      oc += 1",
            "    elif hl.startswith(chr(92)):",
            "      pass",
            "    else:",
            "      oc += 1",
            "      nc += 1",
            "    j += 1",
            "  fixed.append('@@ -%s,%d +%s,%d @@%s' % (hm.group(1), oc, hm.group(2), nc, hm.group(3)) + chr(10))",
            "  i += 1",
            "out = fixed",
            "pathlib.Path('/tmp/_n.diff').write_text(''.join(out))",
        ])
        norm_result = await sbx.exec(
            ["python3", "-c", normalise_script, str(patch_file)],
            timeout=30,
        )
        norm_pf = "/tmp/_n.diff"
        if norm_result.returncode != 0:
            logger.warning(
                "Patch normaliser failed (rc=%d): %s",
                norm_result.returncode,
                (norm_result.stderr or norm_result.stdout)[:300],
            )
            # Fall back to the original patch file
            norm_pf = str(patch_file)

        # Agents commonly apply the patch themselves during exploration before
        # submitting.  Undo any previous (possibly fuzz-applied) application so
        # the scorer works from a clean baseline.  If no prior application
        # exists, the reverse is a harmless no-op.
        await sbx.exec(
            [
                "bash", "-c",
                f"cd {src_q} && "
                f"patch -R -p1 --fuzz=3 --batch < {norm_pf} 2>/dev/null; "
                # Also remove .rej / .orig artefacts from earlier failed attempts.
                f"find {src_q} \\( -name '*.rej' -o -name '*.orig' \\) -delete 2>/dev/null; "
                "true",
            ],
            timeout=60,
        )

        apply_result = await sbx.exec(
            [
                "bash", "-c",
                f"cd {src_q} && "
                f"git apply --whitespace=nowarn {norm_pf} 2>&1 || "
                f"patch -p1 --fuzz=3 --forward < {norm_pf}",
            ],
            timeout=60,
        )
        if apply_result.returncode != 0:
            # Check if the patch is already applied (reverse dry-run)
            reverse_check = await sbx.exec(
                ["bash", "-c", f"cd {src_q} && patch -R -p1 --fuzz=3 --dry-run < {norm_pf}"],
                timeout=60,
            )
            if reverse_check.returncode == 0:
                logger.info("Patch already applied, skipping apply step")
            else:
                combined = (apply_result.stdout + "\n" + apply_result.stderr).strip()
                return Score(
                    value=0.0,
                    answer=ctx.submission,
                    explanation=f"Patch failed to apply: {combined[:500]}",
                )

        # Step 3: Rebuild with ASAN
        # Set AIxCC-compatible env vars for build.sh scripts that expect them
        out_dir = posixpath.dirname(harness_path) if harness_path else "/workspace/build"
        env_prefix = (
            f"SRC={shlex.quote(str(source_dir))} "
            f"OUT={shlex.quote(str(out_dir))} "
            "CC=clang CXX=clang++ "
            "CFLAGS='-fsanitize=address -fno-omit-frame-pointer -g' "
            "CXXFLAGS='-fsanitize=address -fno-omit-frame-pointer -g' "
            "LIB_FUZZING_ENGINE=/usr/lib/llvm-19/lib/libFuzzer.a "
        )
        if build_script:
            build_cmd = f"{env_prefix} bash {shlex.quote(str(build_script))}"
        else:
            build_cmd = (
                f"cd {shlex.quote(str(source_dir))} && make clean 2>/dev/null; "
                f"make CC=clang CFLAGS='-fsanitize=address -fno-omit-frame-pointer -g'"
            )

        build_result = await sbx.exec(
            ["bash", "-c", build_cmd],
            timeout=300,
        )
        if build_result.returncode != 0:
            return Score(
                value=0.0,
                answer=ctx.submission,
                explanation=f"Build failed after patching: {build_result.stderr[:500]}",
            )

        # Step 4: Run all POVs — patched binary should NOT crash
        list_povs = await sbx.exec(
            ["find", pov_dir, "-type", "f"],
            timeout=30,
        )
        pov_files = [
            p.strip() for p in list_povs.stdout.strip().split("\n") if p.strip()
        ]

        if not pov_files:
            return Score(
                value=0.0,
                answer=ctx.submission,
                explanation=f"No POV files found in {pov_dir}",
            )

        any_crash = False
        crash_details: list[str] = []
        for pov_file in pov_files:
            pov_result = await sbx.exec(
                [
                    "bash",
                    "-c",
                    (
                        f"ASAN_OPTIONS=detect_leaks=0:abort_on_error=1 "
                        f"{shlex.quote(str(harness_path))} {shlex.quote(str(pov_file))}"
                    ),
                ],
                timeout=60,
            )
            if pov_result.returncode != 0:
                any_crash = True
                crash_details.append(
                    f"{pov_file}: exit={pov_result.returncode}"
                )

        if any_crash:
            return Score(
                value=0.0,
                answer=ctx.submission,
                explanation=(
                    f"Patched binary still crashes on POVs: "
                    f"{'; '.join(crash_details[:5])}"
                ),
            )

        # Step 5: Run unit tests (if test script path is set and file exists)
        if test_script:
            test_check = await sbx.exec(
                ["test", "-f", test_script],
                timeout=10,
            )
            if test_check.returncode == 0:
                # Ensure scripts are executable (files copied from host may
                # lack the execute bit) and pass AIxCC env vars so test.sh
                # can rebuild / link as needed.
                await sbx.exec(
                    ["bash", "-c", f"chmod +x {shlex.quote(str(test_script))} {src_q}/*.sh 2>/dev/null || true"],
                    timeout=10,
                )
                test_result = await sbx.exec(
                    ["bash", "-c", f"{env_prefix} {shlex.quote(str(test_script))}"],
                    timeout=300,
                )
                if test_result.returncode != 0:
                    return Score(
                        value=0.5 * max_score,
                        answer=ctx.submission,
                        explanation=(
                            "Patch fixes crash but breaks unit tests: "
                            f"{test_result.stderr[:500]}"
                        ),
                    )

        # All checks passed
        return Score(
            value=max_score,
            answer=ctx.submission,
            explanation=(
                f"VALID: Patch builds, fixes {len(pov_files)} POV(s), "
                f"passes unit tests"
            ),
        )

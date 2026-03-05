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
        apply_result = await sbx.exec(
            ["bash", "-c", f"cd {shlex.quote(str(source_dir))} && patch -p1 --forward < {shlex.quote(str(patch_file))}"],
            timeout=60,
        )
        if apply_result.returncode != 0:
            return Score(
                value=0.0,
                answer=ctx.submission,
                explanation=f"Patch failed to apply: {apply_result.stderr[:500]}",
            )

        # Step 3: Rebuild with ASAN
        if build_script:
            build_cmd = f"bash {shlex.quote(str(build_script))}"
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
                test_result = await sbx.exec(
                    ["bash", test_script],
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

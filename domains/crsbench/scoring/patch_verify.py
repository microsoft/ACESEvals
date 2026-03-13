"""CRSBench patch verification scoring strategy.

Verifies agent-submitted patches by:
1. Finding patch file(s) in ``patch_dir`` via ``sandbox().exec()``
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

import asyncio
import logging
import posixpath
import shlex
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from dataclasses import dataclass
from typing import TYPE_CHECKING

# Domain loggers use saber.domains.* namespace so they inherit
# saber's logging configuration and flow through inspect_ai's LogHandler.

from inspect_ai.scorer import Score
from inspect_ai.util import sandbox

from saber.config.models import DomainCriteria
from saber.scoring.context import ScoringContext

if TYPE_CHECKING:
    from inspect_ai.util._sandbox.environment import SandboxEnvironment

    from saber.scoring.templates import TemplateRenderer

logger = logging.getLogger("saber.domains.crsbench.scoring.patch_verify")

# ---------------------------------------------------------------------------
# Timeout constants (seconds)
# ---------------------------------------------------------------------------
_FIND_TIMEOUT = 30
_PATCH_TIMEOUT = 60
_POV_TIMEOUT = 300
_BUILD_TIMEOUT = 3000
_TEST_TIMEOUT = 300

# ---------------------------------------------------------------------------
# Default sandbox paths
# ---------------------------------------------------------------------------
_DEFAULT_SOURCE_DIR = "/workspace/source"
_DEFAULT_BUILD_DIR = "/workspace/build"
_DEFAULT_POV_DIR = "/workspace/povs"
_DEFAULT_PATCH_DIR = "/submit/patches"

# ---------------------------------------------------------------------------
# Score tiers
# ---------------------------------------------------------------------------
_SCORE_PARTIAL = 0.5
_SCORE_ZERO = 0.0

# Timeout for lightweight file-existence / chmod checks (seconds)
_MISC_TIMEOUT = 10


# ---------------------------------------------------------------------------
# Config dataclass — typed access to DomainCriteria extras
# ---------------------------------------------------------------------------
@dataclass(frozen=True)
class _PatchVerifyConfig:
    """Parsed scoring criteria for patch verification."""

    source_dir: str
    build_cwd: str
    build_script: str
    harness_path: str
    pov_dir: str
    test_script: str
    patch_dir: str
    max_score: float

    @property
    def out_dir(self) -> str:
        """Output directory derived from harness path."""
        return posixpath.dirname(self.harness_path) if self.harness_path else _DEFAULT_BUILD_DIR

    @property
    def env_prefix(self) -> str:
        """AIxCC-compatible environment variable prefix for build/test commands."""
        return (
            f"SRC={shlex.quote(self.source_dir)} "
            f"OUT={shlex.quote(self.out_dir)} "
            "CC=clang CXX=clang++ "
            "CFLAGS='-fsanitize=address -fno-omit-frame-pointer -g' "
            "CXXFLAGS='-fsanitize=address -fno-omit-frame-pointer -g' "
        )

    @classmethod
    def from_criteria(
        cls, criteria: DomainCriteria, max_score: float
    ) -> _PatchVerifyConfig:
        """Build config from ``DomainCriteria.model_extra``."""
        extra = criteria.model_extra or {}
        source_dir = extra.get("source_dir") or _DEFAULT_SOURCE_DIR
        return cls(
            source_dir=source_dir,
            build_cwd=extra.get("build_cwd") or source_dir,
            build_script=extra.get("build_script") or "",
            harness_path=extra.get("harness_path") or "",
            pov_dir=extra.get("pov_dir") or _DEFAULT_POV_DIR,
            test_script=extra.get("test_script") or "",
            patch_dir=extra.get("patch_dir") or _DEFAULT_PATCH_DIR,
            max_score=max_score,
        )


# ---------------------------------------------------------------------------
# POV verification result
# ---------------------------------------------------------------------------
@dataclass(frozen=True)
class PovVerifyResult:
    """Result of running POV files against a patched binary.

    Attributes:
        all_passed: True if no POV triggered a crash.
        crash_details: Per-POV crash descriptions (empty when all pass).
        pov_count: Total number of POV files executed.
    """

    all_passed: bool
    crash_details: tuple[str, ...]
    pov_count: int


# ---------------------------------------------------------------------------
# Normaliser script builder
# ---------------------------------------------------------------------------
def _build_normalise_script(source_dir: str) -> str:
    """Build the inline Python normaliser script for a given *source_dir*.

    The normaliser strips absolute source_dir prefixes, ``a/`` ``b/``
    prefixes, backup suffixes (``.bak``, ``.orig``, ``.old``, ``.new``,
    ``~``), timestamps, and re-adds ``a/`` ``b/``.  When the stripped path
    doesn't exist in *source_dir* it searches the tree for a matching
    basename so patches created against ``/tmp`` copies still resolve
    correctly.  Finally, ``@@`` hunk-header line counts are recalculated
    since LLMs frequently get them wrong.
    """
    return "\n".join([
        "import re, sys, os, pathlib",
        f"src = {source_dir!r}",
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
        "pathlib.Path(sys.argv[2]).write_text(''.join(out))",
    ])


# ---------------------------------------------------------------------------
# Network access context manager
# ---------------------------------------------------------------------------
@asynccontextmanager
async def _sandbox_network_access() -> AsyncIterator[None]:
    """Temporarily grant the sandbox container internet access.

    Connects the container to Docker's default ``bridge`` network,
    which provides outbound internet.  The connection is always removed
    in the ``finally`` block, even if an exception is raised.

    This is used during the scorer's build and test steps — the agent
    never has network access during its solve phase.
    """
    container: str | None = None
    connected = False
    try:
        sbx = sandbox()
        conn = await sbx.connection()
        container = conn.container
        if not container:
            logger.warning("Cannot determine container name; skipping network toggle")
            yield
            return

        proc = await asyncio.create_subprocess_exec(
            "docker", "network", "connect", "bridge", container,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
        stdout, stderr = await proc.communicate()
        if proc.returncode == 0:
            connected = True
            logger.info("Enabled network access for container %s", container)
        else:
            # May already be connected, or bridge may not exist
            logger.warning(
                "Failed to connect container %s to bridge (rc=%d): %s",
                container, proc.returncode, stderr.decode(errors="replace").strip(),
            )
        yield
    finally:
        if connected and container:
            proc = await asyncio.create_subprocess_exec(
                "docker", "network", "disconnect", "bridge", container,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
            )
            stdout, stderr = await proc.communicate()
            if proc.returncode == 0:
                logger.info("Disabled network access for container %s", container)
            else:
                logger.warning(
                    "Failed to disconnect container %s from bridge (rc=%d): %s",
                    container, proc.returncode, stderr.decode(errors="replace").strip(),
                )


class CRSBenchPatchVerifyStrategy:
    """Patch verification strategy implementing ``SaberScoringStrategy`` protocol.

    Reads criteria fields from ``DomainCriteria.model_extra``:
      - ``source_dir``: Path to source code in sandbox (default ``/workspace/source``)
      - ``build_cwd``: Directory to ``cd`` into before running build/test scripts
        (default: ``source_dir``).  Allows decoupling the build working directory
        from ``$SRC`` so that ``build.sh`` scripts can reference sibling directories.
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
        renderer: TemplateRenderer | None,
    ) -> Score:
        """Apply patch, rebuild, run POVs, run tests. Return tiered score."""
        criteria = ctx.scorer.criteria
        if not isinstance(criteria, DomainCriteria):
            return Score(
                value=_SCORE_ZERO,
                answer=ctx.submission,
                explanation=f"Expected DomainCriteria, got {type(criteria).__name__}",
            )

        cfg = _PatchVerifyConfig.from_criteria(criteria, ctx.scorer.max_score)
        sbx = sandbox()

        # Step 1: Find patch files
        found_files = await self._find_patch_files(sbx, cfg.patch_dir)
        if found_files is None:
            return Score(
                value=_SCORE_ZERO,
                answer=ctx.submission,
                explanation=f"No patch file found in {cfg.patch_dir}",
            )

        # Step 2: Normalise + apply patches
        applied_count, apply_failures = await self._apply_patches(
            sbx, found_files, cfg.source_dir,
        )
        if applied_count == 0:
            return Score(
                value=_SCORE_ZERO,
                answer=ctx.submission,
                explanation=(
                    f"Patch failed to apply: "
                    f"{'; '.join(apply_failures[:3])}"
                ),
            )

        # Step 3: Rebuild with ASAN
        build_ok, build_stderr = await self._rebuild(sbx, cfg)
        if not build_ok:
            return Score(
                value=_SCORE_ZERO,
                answer=ctx.submission,
                explanation=f"Build failed after patching: {build_stderr}",
            )

        # Step 4: Run all POVs
        pov_result = await self._verify_povs(sbx, cfg.pov_dir, cfg.harness_path)
        if pov_result is None:
            return Score(
                value=_SCORE_ZERO,
                answer=ctx.submission,
                explanation=f"No POV files found in {cfg.pov_dir}",
            )
        if not pov_result.all_passed:
            return Score(
                value=_SCORE_ZERO,
                answer=ctx.submission,
                explanation=(
                    f"Patched binary still crashes on POVs: "
                    f"{'; '.join(pov_result.crash_details[:5])}"
                ),
            )

        # Step 5: Run tests
        test_score = await self._run_tests(sbx, cfg)
        if test_score is not None:
            return test_score

        # All checks passed
        return Score(
            value=cfg.max_score,
            answer=ctx.submission,
            explanation=(
                f"VALID: Patch builds, fixes {pov_result.pov_count} POV(s), "
                f"passes unit tests"
            ),
        )

    # ------------------------------------------------------------------
    # Private helpers — each maps to one logical step
    # ------------------------------------------------------------------

    async def _find_patch_files(
        self,
        sbx: SandboxEnvironment,
        patch_dir: str,
    ) -> list[str] | None:
        """Step 1: find patch files in *patch_dir*. Return ``None`` if none found."""
        find_result = await sbx.exec(
            ["find", patch_dir, "-type", "f"],
            timeout=_FIND_TIMEOUT,
        )
        if find_result.returncode != 0 or not find_result.stdout.strip():
            return None

        found_files = sorted(
            p for p in find_result.stdout.strip().split("\n") if p.strip()
        )
        logger.info("Found %d patch file(s): %s", len(found_files), found_files)
        return found_files

    async def _apply_patches(
        self,
        sbx: SandboxEnvironment,
        found_files: list[str],
        source_dir: str,
    ) -> tuple[int, list[str]]:
        """Step 2: normalise and apply each patch. Return (applied, failures)."""
        src_q = shlex.quote(source_dir)

        # Clean .rej / .orig artefacts from earlier failed attempts
        await sbx.exec(
            [
                "bash", "-c",
                f"find {src_q} \\( -name '*.rej' -o -name '*.orig' \\) "
                f"-delete 2>/dev/null; true",
            ],
            timeout=_FIND_TIMEOUT,
        )

        normalise_script = _build_normalise_script(source_dir)

        apply_failures: list[str] = []
        applied_count = 0

        for idx, pf in enumerate(found_files):
            norm_pf = f"/tmp/_n_{idx}.diff"

            # Normalise this patch file
            norm_result = await sbx.exec(
                ["python3", "-c", normalise_script, pf, norm_pf],
                timeout=_FIND_TIMEOUT,
            )
            if norm_result.returncode != 0:
                logger.warning(
                    "Patch normaliser failed for %s (rc=%d): %s",
                    pf,
                    norm_result.returncode,
                    (norm_result.stderr or norm_result.stdout)[:300],
                )
                # Fall back to the original patch file
                norm_pf = pf

            # Undo any previous application of this specific patch
            await sbx.exec(
                [
                    "bash", "-c",
                    f"cd {src_q} && "
                    f"patch -R -p1 --fuzz=3 --batch < {shlex.quote(norm_pf)} "
                    f"2>/dev/null; true",
                ],
                timeout=_PATCH_TIMEOUT,
            )

            # Apply the patch
            apply_result = await sbx.exec(
                [
                    "bash", "-c",
                    f"cd {src_q} && "
                    f"git apply --whitespace=nowarn {shlex.quote(norm_pf)} 2>&1 || "
                    f"patch -p1 --fuzz=3 --forward < {shlex.quote(norm_pf)}",
                ],
                timeout=_PATCH_TIMEOUT,
            )
            if apply_result.returncode != 0:
                # Check if the patch is already applied (reverse dry-run)
                reverse_check = await sbx.exec(
                    [
                        "bash", "-c",
                        f"cd {src_q} && patch -R -p1 --fuzz=3 --dry-run "
                        f"< {shlex.quote(norm_pf)}",
                    ],
                    timeout=_PATCH_TIMEOUT,
                )
                if reverse_check.returncode == 0:
                    logger.info("Patch %s already applied, skipping", pf)
                    applied_count += 1
                else:
                    combined = (
                        apply_result.stdout + "\n" + apply_result.stderr
                    ).strip()
                    apply_failures.append(f"{pf}: {combined[:200]}")
                    logger.warning("Patch %s failed to apply: %s", pf, combined[:200])
            else:
                applied_count += 1

        return applied_count, apply_failures

    async def _rebuild(
        self,
        sbx: SandboxEnvironment,
        cfg: _PatchVerifyConfig,
    ) -> tuple[bool, str]:
        """Step 3: rebuild with ASAN. Return (success, stderr_tail)."""
        # Ensure $LIB_FUZZING_ENGINE resolves to an actual file.
        await sbx.exec(
            [
                "bash", "-c",
                'if [ -n "$LIB_FUZZING_ENGINE" ] && [ ! -f "$LIB_FUZZING_ENGINE" ]; then '
                '  FUZZER_RT=$(find /usr/local/lib /usr/lib -name "libclang_rt.fuzzer.a" -path "*/x86_64*" 2>/dev/null | head -1); '
                '  if [ -n "$FUZZER_RT" ]; then '
                '    ln -sf "$FUZZER_RT" "$LIB_FUZZING_ENGINE"; '
                '  fi; '
                'fi',
            ],
            timeout=_FIND_TIMEOUT,
        )

        build_cwd_q = shlex.quote(cfg.build_cwd)
        if cfg.build_script:
            build_cmd = f"cd {build_cwd_q} && {cfg.env_prefix} bash -eu {shlex.quote(cfg.build_script)}"
        else:
            build_cmd = (
                f"cd {build_cwd_q} && make clean 2>/dev/null; "
                f"make CC=clang CFLAGS='-fsanitize=address -fno-omit-frame-pointer -g'"
            )

        async with _sandbox_network_access():
            build_result = await sbx.exec(
                ["bash", "-c", build_cmd],
                timeout=_BUILD_TIMEOUT,
            )

        return build_result.returncode == 0, build_result.stderr[-2000:]

    async def _verify_povs(
        self,
        sbx: SandboxEnvironment,
        pov_dir: str,
        harness_path: str,
    ) -> PovVerifyResult | None:
        """Step 4: run all POVs. Return ``None`` when no POVs found."""
        list_povs = await sbx.exec(
            ["find", pov_dir, "-type", "f"],
            timeout=_FIND_TIMEOUT,
        )
        pov_files = [
            p.strip() for p in list_povs.stdout.strip().split("\n") if p.strip()
        ]
        if not pov_files:
            return None

        crash_details: list[str] = []
        for pov_file in pov_files:
            pov_result = await sbx.exec(
                [
                    "bash",
                    "-c",
                    (
                        f"ASAN_OPTIONS=detect_leaks=0:abort_on_error=1 "
                        f"{shlex.quote(harness_path)} {shlex.quote(pov_file)}"
                    ),
                ],
                timeout=_POV_TIMEOUT,
            )
            if pov_result.returncode != 0:
                crash_details.append(
                    f"{pov_file}: exit={pov_result.returncode}"
                )

        return PovVerifyResult(
            all_passed=len(crash_details) == 0,
            crash_details=tuple(crash_details),
            pov_count=len(pov_files),
        )

    async def _run_tests(
        self,
        sbx: SandboxEnvironment,
        cfg: _PatchVerifyConfig,
    ) -> Score | None:
        """Step 5: run tests. Return ``Score`` for partial tier, ``None`` if tests pass/skipped."""
        if not cfg.test_script:
            return None

        test_check = await sbx.exec(
            ["test", "-f", cfg.test_script],
            timeout=_MISC_TIMEOUT,
        )
        if test_check.returncode != 0:
            return None

        # Ensure scripts are executable
        src_q = shlex.quote(cfg.source_dir)
        await sbx.exec(
            ["bash", "-c", f"chmod +x {shlex.quote(cfg.test_script)} {src_q}/*.sh 2>/dev/null || true"],
            timeout=_MISC_TIMEOUT,
        )

        build_cwd_q = shlex.quote(cfg.build_cwd)

        try:
            async with _sandbox_network_access():
                test_result = await sbx.exec(
                    ["bash", "-c", f"cd {build_cwd_q} && {cfg.env_prefix} {shlex.quote(cfg.test_script)}"],
                    timeout=_TEST_TIMEOUT,
                )
        except (TimeoutError, asyncio.TimeoutError):
            return Score(
                value=_SCORE_PARTIAL * cfg.max_score,
                answer=None,
                explanation=f"Patch fixes crash but test.sh timed out after {_TEST_TIMEOUT}s",
            )

        if test_result.returncode != 0:
            return Score(
                value=_SCORE_PARTIAL * cfg.max_score,
                answer=None,
                explanation=(
                    "Patch fixes crash but breaks unit tests: "
                    f"{test_result.stderr[-2000:]}"
                ),
            )

        return None

"""CRSBench vulnerability patching domain for Inspect AI.

This module exposes the CRSBench domain as an Inspect AI task that can be
evaluated with commands like:

    inspect eval domains/crsbench --model openai/gpt-4
    inspect eval domains/crsbench -T task_filter=sanity_* --model openai/gpt-4
"""

from inspect_ai import Task, task

from saber.task import create_task

_GIT_INIT_SETUP = """\
#!/usr/bin/env bash
set -euo pipefail
mkdir -p /workspace/source
cd /workspace/source

# Remove nested .git directories so subdirectories (e.g. mock-c/, curl/)
# are tracked as regular files instead of being treated as embedded
# submodules.  Harmless no-op when none exist.
find . -mindepth 2 -name .git -exec rm -rf {} + 2>/dev/null || true

# Ignore build artifacts so they never pollute git diff output.
cat > .gitignore <<'IGNORE'
*.o
*.a
*.so
*.class
*.jar
*.pyc
__pycache__/
IGNORE

git init
git checkout -b main 2>/dev/null || true
git config user.email "sandbox@saber"
git config user.name "sandbox"
git add -A
git commit --allow-empty -m "initial" --quiet
"""


# Parameters consumed by setup hooks (setup.py) or crsbench itself
# that must NOT leak through to the agent factory via **kwargs.
_DOMAIN_ONLY_PARAMS = frozenset({
    "dataset",
    "data_dir",
    "build",
    "rebuild_images",
})

# The ``lite`` dataset: 60 representative tasks selected from the full
# competition set.  One task per unique project, 60 projects chosen to
# maximise coverage of project categories, languages, and sources.
# Cross-source duplicates (projects in both afc and atlanta) keep a mix
# of both sources.  Near-duplicates (libavif_orig, activemq_var) and
# low-prominence/niche projects were dropped to reach 60.
#
# Language balance: 29 C/C++, 31 Java.
# Source balance: 15 afc, 1 asc, 44 atlanta.
_LITE_TASK_IDS: frozenset[str] = frozenset({
    # --- afc (15) ---
    "afc_apache_commons_compress_delta_01__CompressTarFuzzer__cpv_0__bugfix",
    "afc_curl_delta_01__curl_fuzzer_ws__cpv_0__bugfix",
    "afc_dav1d_full_01__dav1d_fuzzer_mt_NO_OOM__cpv_0__bugfix",
    "afc_freerdp_delta_01__TestFuzzCryptoCertificateDataSetPEM__cpv_0__bugfix",
    "afc_libavif_delta_02__avif_yuvrgb_fuzzer__cpv_0__bugfix",
    "afc_libexif_delta_01__exif_from_data_fuzzer__cpv_2__bugfix",
    "afc_libpng_delta_01__libpng_read_fuzzer__cpv_0__bugfix",
    "afc_log4j2_delta_01__SimpleLoggerFuzzer__cpv_0__bugfix",
    "afc_pdfbox_delta_01__PDFOCRFuzzer__cpv_0__bugfix",
    "afc_shadowsocks_full_01__json_fuzz__cpv_0__bugfix",
    "afc_sqlite3_delta_01__customfuzz3__cpv_0__bugfix",
    "afc_systemd_full_01__fuzz_catalog__cpv_1__bugfix",
    "afc_wireshark_delta_01__handler_ber__cpv_0__bugfix",
    "afc_xz_full_01__fuzz_encode_stream__cpv_0__bugfix",
    "afc_zookeeper_delta_01__MessageTrackerPeekReceivedFuzzer__cpv_0__bugfix",
    # --- asc (1) ---
    "asc_nginx_delta_01__mail_request_harness__cpv_11__bugfix",
    # --- atlanta (44) ---
    "atlanta_activemq_delta_01__ActivemqOne__cpv_0__bugfix",
    "atlanta_apache_commons_validator_delta_01__UrlValidator2Fuzzer__cpv_0__bugfix",
    "atlanta_apache_poi_full_01__POIHDGFFuzzer__cpv_3__bugfix",
    "atlanta_batik_delta_01__BatikOneFDP__cpv_1__bugfix",
    "atlanta_bcel_delta_01__BCELOneFDP__cpv_1__bugfix",
    "atlanta_beanutils_full_01__BeanUtilsOne__cpv_0__bugfix",
    "atlanta_binutils_delta_01__fuzz_as__cpv_0__bugfix",
    "atlanta_cron_utils_delta_01__CronUtilsOneFDP__cpv_1__bugfix",
    "atlanta_cxf_full_01__CXFOne__cpv_0__bugfix",
    "atlanta_feign_full_01__BodyTemplateFuzzer__cpv_0__bugfix",
    "atlanta_freetype2_delta_01__cff_ftengine__cpv_1__bugfix",
    "atlanta_gpac_delta_01__fuzz_probe_analyze__cpv_0__bugfix",
    "atlanta_htmlunit_delta_01__HtmlunitOneFDP__cpv_1__bugfix",
    "atlanta_imaging_delta_01__ImagingOne__cpv_0__bugfix",
    "atlanta_jackson_databind_delta_01__JacksonDatabindOneFDP__cpv_1__bugfix",
    "atlanta_jakarta_mail_api_delta_01__MailApiHarnessOneFDP__cpv_1__bugfix",
    "atlanta_jenkins_delta_01__JenkinsFive__cpv_14__bugfix",
    "atlanta_jq_delta_01__jq_fuzz_fixed__cpv_0__bugfix",
    "atlanta_json_java_full_01__JsonJavaFuzzer__cpv_0__bugfix",
    "atlanta_jsoup_full_01__HtmlFuzzer__cpv_1__bugfix",
    "atlanta_keycloak_delta_01__ServicesUtilsFuzzer__cpv_0__bugfix",
    "atlanta_libavc_full_01__mvc_dec_fuzzer__cpv_1__bugfix",
    "atlanta_libjpeg_full_01__libjpeg_cjpeg_fuzzer__cpv_0__bugfix",
    "atlanta_libssh2_delta_01__ssh2_client_fuzzer__cpv_0__bugfix",
    "atlanta_libtiff_full_01__tiff_open__cpv_1__bugfix",
    "atlanta_libxml2_delta_01__api__cpv_0__bugfix",
    "atlanta_mongoose_delta_01__fuzz__cpv_0__bugfix",
    "atlanta_mosquitto_delta_01__broker_fuzz_test_config__cpv_0__bugfix",
    "atlanta_nasm_delta_01__fuzz_nasm__cpv_0__bugfix",
    "atlanta_netty_delta_01__ByteBufUtilFuzzer__cpv_0__bugfix",
    "atlanta_pac4j_full_01__Pac4jOne__cpv_0__bugfix",
    "atlanta_pcre2_full_01__pcre2_fuzzer__cpv_0__bugfix",
    "atlanta_php_delta_01__php_fuzz_execute__cpv_0__bugfix",
    "atlanta_rdf4j_full_01__Rdf4jOne__cpv_0__bugfix",
    "atlanta_shiro_full_01__ShiroOne__cpv_0__bugfix",
    "atlanta_sleuthkit_delta_01__sleuthkit_fls_ntfs_fuzzer__cpv_0__bugfix",
    "atlanta_snappy_java_delta_01__BitShuffleFuzzer__cpv_1__bugfix",
    "atlanta_spring_framework_full_01__SpelExpressionFuzzer__cpv_0__bugfix",
    "atlanta_sqlite_jdbc_delta_01__SqliteConnectionFuzzer__cpv_0__bugfix",
    "atlanta_struts_delta_01__StrutsOne__cpv_0__bugfix",
    "atlanta_tika_delta_01__TikaOne__cpv_0__bugfix",
    "atlanta_tmux_delta_01__input_fuzzer__cpv_0__bugfix",
    "atlanta_user_nginx_full_01__pov_harness__cpv_0__bugfix",
    "atlanta_xstream_full_01__XmlFuzzer__cpv_0__bugfix",
})


@task
def crsbench(**kwargs: str | None) -> Task:
    """CRSBench vulnerability patching domain.

    Vulnerability patching benchmark based on CRSBench — agent receives
    vulnerable source code, crash-triggering POVs, and must write a
    source-code patch that fixes the crash without breaking functionality.

    Setup hooks (data download, image build, task generation) are
    auto-discovered via ``get_hooks()`` in ``setup.py``.

    Args:
        **kwargs: Keyword arguments forwarded to ``create_task``
            (e.g., task_filter, agent, rebuild, run_preflight,
            keep_permanent, persona_file, dataset, build, rebuild_images).

    Returns:
        Fully configured inspect_ai Task.
    """
    # When dataset=lite, apply task-level filtering.  The setup hooks
    # handle benchmark-level scoping (only download/build the 89 lite
    # benchmarks) via _DATASET_GROUPS["lite"] in setup.py, but those
    # benchmarks contain more tasks than the 100 in the lite set, so
    # we inject a task_filter to narrow down at the ConfigLoader level.
    dataset = kwargs.get("dataset")
    if dataset == "lite":
        kwargs["task_filter"] = ",".join(sorted(_LITE_TASK_IDS))

    # Strip domain-only params so they don't leak to the agent factory
    # (e.g. react() would fail on unknown kwargs like 'dataset').
    # NOTE: ``dataset`` is intentionally kept — it's a named parameter of
    # ``create_task()`` and must reach the setup hooks (``get_hooks()``)
    # so they can scope downloads/builds to the requested subset.
    task_kwargs = {k: v for k, v in kwargs.items() if k not in _DOMAIN_ONLY_PARAMS}
    task_kwargs["dataset"] = dataset  # forward to create_task → get_hooks
    result = create_task(**task_kwargs)
    # Inject git init setup into every sample so agents can use `git diff`
    # to generate patches instead of manually crafting unified diffs.
    # Unconditionally overwrite — git init must always run, even if YAML
    # defines a setup script via a future TaskConfig.setup field.
    for sample in result.dataset:
        sample.setup = _GIT_INIT_SETUP
    return result

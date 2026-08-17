"""安全测试：密钥脱敏与扫描门禁。

覆盖：
    1. redact() 对各家密钥格式生效，且不误伤正常文本；
    2. logger 写入的日志文件中不含密钥（含 traceback 场景）；
    3. 运行时登记的精确密钥必定被抹除；
    4. 未捕获异常经 excepthook 输出时已脱敏；
    5. secret_scan 能抓到植入的密钥（含 .pyc 二进制），
       且放过占位符与环境变量读取；
    6. 项目源码树整体无硬编码密钥。

关于测试夹具的写法：
    本文件所有假密钥都用 `_fake_key(前缀, 主体)` 在运行时拼接，
    源码里不出现任何「完整可识别」的密钥字面量。
    这样 test_project_tree_clean 扫描整棵树时，本文件自身是干净的，
    无需依赖行内抑制注释 —— 抑制注释一旦滥用就等于关掉了扫描。

运行：
    python tests/test_security_redaction.py
"""
from __future__ import annotations

import io
import os
import sys
import tempfile

_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if _ROOT not in sys.path:
    sys.path.insert(0, _ROOT)
sys.path.insert(0, os.path.join(_ROOT, "build_tools"))

from futures_quant.utils.redact import (  # noqa: E402
    MASK, clear_registered_secrets, redact, redact_mapping, register_secret,
)
from futures_quant.utils.logger import get_logger  # noqa: E402
import secret_scan  # noqa: E402

_PASS = 0
_FAIL = 0


def _fake_key(prefix: str, body: str) -> str:
    """运行时拼接假密钥，避免本文件源码出现完整密钥字面量。"""
    return prefix + body


def check(name: str, cond: bool, detail: str = "") -> None:
    global _PASS, _FAIL
    if cond:
        _PASS += 1
        print(f"  [OK]   {name}")
    else:
        _FAIL += 1
        print(f"  [FAIL] {name}  {detail}")


# ---------------------------------------------------------------------------
def test_redact_formats() -> None:
    print("\n[1] 各类密钥格式脱敏")
    sk = _fake_key("sk-", "A1b2C3d4E5f6G7h8J9k0L1m2N3o4P5q6")
    bearer = _fake_key("", "qWeRtY7uIoP9aSdF2gHjKl4zXcVb")
    akid = _fake_key("AKIA", "IOSFODNN7REALKEY")
    gh = _fake_key("ghp_", "Qw3rTy7UiOp9AsDf2GhJkL4zXcVbNm6QwEr")
    goog = _fake_key("AIza", "SyA1b2C3d4E5f6G7h8J9k0L1m2N3o4P5q6R7")
    jwt = (_fake_key("eyJ", "hbGciOiJIUzI1NiJ9") + "."
           + "eyJzdWIiOiIxMjMifQ" + "." + "Qw3rTy7UiOp9AsDf")
    pw = _fake_key("", "hunter2SecretPass")
    qkey = _fake_key("", "s3cr3tV4lu3xyz789")
    dkey = _fake_key("", "zZq8vN3mK1pL5xR7")

    cases = [
        ("OpenAI 风格", f"key={sk}", sk),
        ("Bearer 头", f"Authorization: Bearer {bearer}", bearer),
        ("AWS AKID", akid, akid),
        ("GitHub token", gh, gh),
        ("Google key", goog, goog),
        ("JWT", f"token {jwt}", jwt),
        ("URL 内嵌凭据", f"https://admin:{pw}@api.example.com/v1", pw),
        ("查询参数", f"GET /v1/chat?api_key={qkey}&n=1", qkey),
        ("字典赋值", "{'api_key': '" + dkey + "'}", dkey),
    ]
    for label, raw, secret_part in cases:
        out = redact(raw)
        check(f"{label} 已脱敏", secret_part not in out, f"输出={out!r}")


def test_no_false_positive() -> None:
    print("\n[2] 正常文本不被误伤")
    samples = [
        "回测完成：共 339 笔成交，胜率 52.3%",
        "合约 rb.SHFE 最新价 3521.00，支撑 3480",
        "已加载 4208 根 K 线，来源 akshare",
    ]
    for s in samples:
        check(f"保持原样：{s[:20]}...", redact(s) == s, f"输出={redact(s)!r}")


def test_registered_secret() -> None:
    print("\n[3] 运行时登记的精确密钥")
    clear_registered_secrets()
    # 一个不含任何键名前缀、也不匹配任何通用规则的「奇怪」令牌，
    # 放在纯叙述性句子里，确保只有「精确登记」这一条机制能抹掉它。
    weird = "QV7pancake9moonlight2"
    plain = f"服务端返回的凭据为 {weird} 请勿外传"
    check("登记前原样输出", weird in redact(plain), f"输出={redact(plain)!r}")
    register_secret(weird)
    check("登记后必被抹除", weird not in redact(plain))
    check("抹除处有掩码标记", MASK in redact(plain))
    clear_registered_secrets()


def test_mapping() -> None:
    print("\n[4] headers 字典脱敏")
    h = {"Authorization": "Bearer " + _fake_key("sk-", "aBcDeFgHiJkLmNoPqRsT"),
         "Content-Type": "application/json",
         "X-Api-Key": _fake_key("", "zZq8vN3mK1pL5xR7")}
    out = redact_mapping(h)
    check("Authorization 被抹", out["Authorization"] == MASK, str(out))
    check("X-Api-Key 被抹", out["X-Api-Key"] == MASK, str(out))
    check("Content-Type 保留",
          out["Content-Type"] == "application/json", str(out))


def test_logger_file() -> None:
    print("\n[5] 日志文件不落密钥（含 traceback）")
    secret = _fake_key("sk-", "LoGgEr1TeSt2KeY3wXyZ7mNpQrSt")
    with tempfile.TemporaryDirectory() as td:
        log = get_logger(name="sec_test", log_dir=td, to_console=False)
        log.info("直接打印密钥 %s", secret)
        log.info(f"f-string 密钥 {secret}")
        try:
            raise RuntimeError(f"异常消息里带密钥 {secret}")
        except RuntimeError:
            log.exception("捕获异常")
        for h in log.handlers:
            h.flush()
        path = os.path.join(td, "sec_test.log")
        content = open(path, encoding="utf-8").read()
        check("日志文件中无明文密钥", secret not in content,
              f"文件内容片段={content[:200]!r}")
        check("日志中出现掩码", MASK in content)
        check("traceback 仍可读（保留异常类型）", "RuntimeError" in content)
        for h in list(log.handlers):
            h.close()
            log.removeHandler(h)


def test_excepthook() -> None:
    print("\n[6] 未捕获异常输出脱敏")
    from futures_quant.utils import redact as rd
    secret = _fake_key("sk-", "ExCePtHoOk1TeSt2wXyZ7mNpQr")
    buf = io.StringIO()
    old = sys.stderr
    try:
        sys.stderr = buf
        try:
            raise ValueError(f"炸了，密钥是 {secret}")
        except ValueError:
            rd._redacting_excepthook(*sys.exc_info())
    finally:
        sys.stderr = old
    out = buf.getvalue()
    check("excepthook 输出无明文密钥", secret not in out, f"输出={out[:200]!r}")
    check("excepthook 输出含掩码", MASK in out)
    check("仍保留异常类型", "ValueError" in out)


def test_entrypoint_installs_hooks() -> None:
    """程序入口必须真的装上全局脱敏钩子。

    脱敏模块写得再好，入口不调用就等于没有 —— 这条断言防的正是这种
    「模块存在但没接线」的假安全。
    """
    print("\n[7] 程序入口已接线全局脱敏")
    import subprocess

    # 在子进程里以非 __main__ 名称执行 main.py：顶层语句（含钩子安装）
    # 会完整跑一遍，但不会触发 UI 启动。这样测的是真实启动路径，
    # 而不是「我在测试里自己调一次 install_global_redaction」的自欺。
    probe_src = (
        "import os, runpy, sys\n"
        f"ROOT = r'{_ROOT}'\n"
        "sys.path.insert(0, ROOT)\n"
        "runpy.run_path(os.path.join(ROOT, 'main.py'), run_name='qv_probe')\n"
        "import futures_quant.utils.redact as rd\n"
        "print('EXCEPTHOOK_OK' if sys.excepthook is rd._redacting_excepthook"
        " else 'EXCEPTHOOK_MISSING')\n"
        "print('INSTALLED_OK' if rd._installed else 'INSTALLED_MISSING')\n"
    )
    with tempfile.TemporaryDirectory() as td:
        probe_path = os.path.join(td, "probe_entry_hooks.py")
        with open(probe_path, "w", encoding="utf-8") as fh:
            fh.write(probe_src)
        try:
            res = subprocess.run([sys.executable, probe_path], cwd=_ROOT,
                                 capture_output=True, text=True, timeout=180)
            out = res.stdout + res.stderr
        except Exception as exc:
            out = f"<子进程失败 {exc}>"
    check("main.py 启动即替换 sys.excepthook", "EXCEPTHOOK_OK" in out, out[-300:])
    check("main.py 启动即安装全局脱敏", "INSTALLED_OK" in out, out[-300:])


def test_scanner() -> None:
    print("\n[8] 密钥扫描门禁")
    planted = _fake_key("sk-", "Sc4nN3r1T3stWxYz7mNpQrStUvGh")
    with tempfile.TemporaryDirectory() as td:
        leak = os.path.join(td, "leak.py")
        clean = os.path.join(td, "clean.py")
        with open(leak, "w", encoding="utf-8") as f:
            f.write(f'API_KEY = "{planted}"\n')
        with open(clean, "w", encoding="utf-8") as f:
            f.write('import os\n'
                    'KEY = os.environ.get("QV_LLM_KEY", "")\n'
                    'DOC = "sk-your-key-here-xxxx"\n')

        hits = secret_scan.scan_paths([leak])
        check("能抓到植入的密钥", len(hits) > 0)

        hits2 = secret_scan.scan_paths([clean])
        check("放过环境变量读取与占位符", len(hits2) == 0,
              f"误报={[str(h) for h in hits2]}")

        # 二进制场景：编译成 pyc 后仍应被抓到（编译不是加密）
        import py_compile
        pyc = py_compile.compile(leak, cfile=os.path.join(td, "leak.pyc"),
                                 doraise=True)
        hits3 = secret_scan.scan_paths([pyc], binary_only=True)
        check("能从 .pyc 二进制中抓到密钥", len(hits3) > 0,
              "编译不是加密，必须能扫出来")

        # 行内抑制标记应当生效
        supp = os.path.join(td, "suppressed.py")
        with open(supp, "w", encoding="utf-8") as f:
            f.write(f'DEMO = "{planted}"  # secret-scan: allow\n')
        hits4 = secret_scan.scan_paths([supp])
        check("行内抑制标记生效", len(hits4) == 0,
              f"仍命中={[str(h) for h in hits4]}")


def test_scanner_precision() -> None:
    """规则精度双向回归。

    历史教训：为了消掉打包产物里第三方库的 sk- 误报，曾把规则收紧成
    「排除大写字母开头」，结果所有大写开头的**真密钥**被静默放过 ——
    消误报的补丁反而炸开了一个漏检大洞。
    此用例把两个方向同时钉死：良性串不许命中，真密钥一个都不许漏。
    """
    print("\n[8b] 扫描规则精度（误报 / 漏检 双向）")

    # 打包产物中已核实的第三方良性字符串（都是连字符拼接的单词）
    benign = [
        _fake_key("sk-", "ecdsa-sha2-nistp256-cert-v01@openssh.com"),  # libssh2
        _fake_key("sk-", "ssh-ed25519-cert-v01@openssh.com"),          # libssh2
        _fake_key("sk-", "Kamchatski-standaardtydry"),                 # babel 时区名
        _fake_key("sk-", "definition-1470764550877"),                  # 示例 JSON
    ]
    # 各种形态的真密钥，一个都不许漏
    real = [
        _fake_key("sk-", "g7Jn2whWMTeAO4ocaPppyC0eftaC4c6hW6m46GTdT5SXuGGr"),
        _fake_key("sk-", "Sc4nN3r1T3stWxYz7mNpQrStUvGh"),      # 大写开头
        _fake_key("sk-", "QwErTyUiOpAsDfGhJkLzXcVbNm"),        # 全字母、无数字
        _fake_key("sk-proj-", "Ab3dEf6hIj9lMn2pQr5tUv8xYz1bCd4e"),
        _fake_key("sk-ant-api03-", "Xy7-Zk2_Ab3dEf6hIj9lMn2pQr5tUv8xYz1bCd4eFg7hIj0k"),
    ]

    with tempfile.TemporaryDirectory() as td:
        # 良性串写成二进制文件，走与产物扫描同一条码路
        bpath = os.path.join(td, "thirdparty.bin")
        with open(bpath, "wb") as f:
            f.write(b"\x00\x01".join(s.encode() for s in benign))
        fp = secret_scan.scan_paths([bpath], binary_only=True)
        check("第三方良性字符串不误报", len(fp) == 0,
              f"误报={[str(h) for h in fp]}")

        missed = []
        for i, key in enumerate(real):
            kpath = os.path.join(td, f"real_{i}.bin")
            with open(kpath, "wb") as f:
                f.write(b"\x00" + key.encode() + b"\x00")
            if not secret_scan.scan_paths([kpath], binary_only=True):
                missed.append(key[:10] + "...")
        check("各形态真密钥无漏检", not missed, f"漏检={missed}")


def test_credential_file_gate() -> None:
    """本地凭据文件不得混入分发产物。

    密钥扫描靠 sk- / -----BEGIN PRIVATE KEY----- 这类特征前缀工作，
    而期货账户凭据（broker_id / user_id / password）没有任何可匹配的前缀，
    字节级扫描对它完全无效 —— 只能靠文件名黑名单兜底。

    历史问题：spec 曾整目录打包 config/，把存放实盘账号密码的
    ctp_settings.json 一并塞进面向公众分发的 exe。
    """
    print("\n[10] 产物凭据文件门禁")

    sys.path.insert(0, os.path.join(_ROOT, "build_tools"))
    import build_exe

    def gate_hits(root: str) -> list[str]:
        """复刻 build_exe._verify_artifact 里的凭据文件判定。"""
        hits = []
        for dirpath, _dirs, files in os.walk(root):
            for f in files:
                low = f.lower()
                if low in build_exe._ARTIFACT_CRED_ALLOW:
                    continue
                if low in build_exe._FORBIDDEN_IN_ARTIFACT or low.endswith(
                        (".local.json", ".secret.json", ".pem", ".key")):
                    hits.append(os.path.relpath(os.path.join(dirpath, f), root))
        return hits

    with tempfile.TemporaryDirectory() as td:
        cfg = os.path.join(td, "_internal", "config")
        os.makedirs(cfg)
        # 应当被拦下的
        must_block = [
            "ctp_settings.json", "secrets.json", "credentials.json",
            "upstream.json", "prod.local.json", "server.key",
        ]
        # 应当放行的
        must_pass = [
            "ctp_settings.example.json", "settings.json", "cacert.pem",
        ]
        for name in must_block + must_pass:
            with open(os.path.join(cfg, name), "w", encoding="utf-8") as f:
                f.write("{}\n")

        hits = set(os.path.basename(h) for h in gate_hits(td))

        missed = [n for n in must_block if n not in hits]
        check("凭据文件全部被拦下", not missed, f"漏拦={missed}")

        wrong = [n for n in must_pass if n in hits]
        check("模板与 CA 信任链未被误拦", not wrong, f"误拦={wrong}")

    # 与 spec 的源头名单保持一致，避免两处各改各的
    spec_path = os.path.join(_ROOT, "build_tools", "futures_qt.spec")
    with open(spec_path, encoding="utf-8") as f:
        spec_src = f.read()
    unsynced = [n for n in build_exe._FORBIDDEN_IN_ARTIFACT
                if n.endswith(".json") and n not in spec_src]
    check("spec 与产物门禁名单同步", not unsynced,
          f"spec 中缺失={unsynced}")

    # spec 不得退回「整目录打包 config」的写法
    check("spec 未整目录打包 config",
          'datas.append((os.path.join(ROOT, "config"), "config"))' not in spec_src,
          "spec 又改回了整目录收集，凭据文件会重新泄露")


def test_project_tree_clean() -> None:
    print("\n[9] 项目源码树整体扫描")
    # 历史泄露密钥（拼接构造，避免本文件出现完整字面量）
    old_key = _fake_key("sk-", "g7Jn2whWMTeAO4ocaPppyC0eftaC4c6hW6m46GTdT5SXuGGr")
    hits = secret_scan.scan_paths(
        [_ROOT], literals=[old_key], skip_dirs=["dist", "build", "tmp"])
    check("源码树无硬编码密钥", len(hits) == 0,
          f"命中={[str(h) for h in hits[:5]]}")


def main() -> int:
    print("=" * 60)
    print("安全测试：密钥脱敏与扫描门禁")
    print("=" * 60)
    test_redact_formats()
    test_no_false_positive()
    test_registered_secret()
    test_mapping()
    test_logger_file()
    test_excepthook()
    test_entrypoint_installs_hooks()
    test_scanner()
    test_scanner_precision()
    test_credential_file_gate()
    test_project_tree_clean()
    print("\n" + "=" * 60)
    print(f"通过 {_PASS} 项，失败 {_FAIL} 项")
    print("=" * 60)
    return 1 if _FAIL else 0


if __name__ == "__main__":
    raise SystemExit(main())

from pathlib import Path

from app.engine import parse_cfst_csv


def test_parse_cfst_csv_keeps_zero_loss_and_sorts(tmp_path: Path):
    result = tmp_path / "result.csv"
    result.write_text(
        "IP 地址,已发送,已接收,丢包率,平均延迟,下载速度(MB/s),地区码\n"
        "192.0.2.10,4,4,0.00,100,2.50,LAX\n"
        "192.0.2.11,4,3,0.25,80,9.00,SJC\n"
        "192.0.2.12,4,4,0.00,90,5.00,HKG\n",
        encoding="utf-8",
    )
    assert parse_cfst_csv(result, 10) == ["192.0.2.12", "192.0.2.10"]


def test_parse_cfst_csv_rejects_unexpected_columns(tmp_path: Path):
    result = tmp_path / "result.csv"
    result.write_text("address,speed\n192.0.2.1,1\n", encoding="utf-8")
    try:
        parse_cfst_csv(result, 10)
    except ValueError as exc:
        assert "CSV" in str(exc)
    else:
        raise AssertionError("expected invalid CSV columns to be rejected")

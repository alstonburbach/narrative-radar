from app import main as cli


def test_cli_parser_supports_offline_json_mode():
    args = cli.build_parser().parse_args(
        ["0xtest", "--chain", "base", "--no-web", "--json", "--paper-usd", "25"]
    )

    assert args.contract == "0xtest"
    assert args.chain == "base"
    assert args.no_web is True
    assert args.json is True
    assert args.paper_usd == 25

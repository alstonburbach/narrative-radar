from app.research_domains import source_domain_family


def test_source_domain_family_collapses_ordinary_subdomains():
    assert source_domain_family("https://docs.example.com/a") == "example.com"
    assert source_domain_family("https://blog.example.com/b") == "example.com"


def test_source_domain_family_handles_common_multi_part_suffixes():
    assert source_domain_family("https://news.example.co.uk/story") == "example.co.uk"


def test_source_domain_family_preserves_shared_host_publishers():
    assert source_domain_family("https://project.github.io/docs") == "project.github.io"


def test_source_domain_family_preserves_ip_addresses():
    assert source_domain_family("https://127.0.0.1/page") == "127.0.0.1"

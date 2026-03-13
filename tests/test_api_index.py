"""Tests for the API index module."""

from __future__ import annotations

import pytest

from mikrotik_mcp.api_index import ApiIndex


@pytest.fixture(scope="module")
def api_index() -> ApiIndex:
    """Load the real OAS2 spec once for all tests in this module."""
    return ApiIndex()


# ------------------------------------------------------------------
# Loading & indexing
# ------------------------------------------------------------------


class TestApiIndexLoading:
    def test_loads_oas2_spec(self, api_index: ApiIndex) -> None:
        assert api_index.endpoint_count > 500

    def test_filters_scripting_commands(self, api_index: ApiIndex) -> None:
        for cmd in ("/if", "/foreach", "/while", "/put", "/global", "/local", "/for"):
            results = api_index.search(cmd.strip("/"))
            paths = [e.path for e in results]
            assert cmd not in paths, f"Scripting command {cmd} should be filtered"

    def test_consolidates_crud_actions(self, api_index: ApiIndex) -> None:
        results = api_index.search("ip address", limit=5)
        ip_addr = next((e for e in results if e.path == "/ip/address"), None)
        assert ip_addr is not None, "/ip/address not found"
        for action in ("add", "remove", "set", "print"):
            assert action in ip_addr.actions, f"Missing action: {action}"

    def test_has_id_flag(self, api_index: ApiIndex) -> None:
        results = api_index.search("ip address", limit=5)
        ip_addr = next((e for e in results if e.path == "/ip/address"), None)
        assert ip_addr is not None
        assert ip_addr.has_id is True

    def test_collects_params(self, api_index: ApiIndex) -> None:
        results = api_index.search("firewall filter", limit=5)
        fw = next((e for e in results if e.path == "/ip/firewall/filter"), None)
        assert fw is not None
        for param in ("chain", "action", "src-address"):
            assert param in fw.params, f"Missing param: {param}"

    def test_preserves_domain_actions(self, api_index: ApiIndex) -> None:
        results = api_index.search("dhcp lease make-static", limit=10)
        paths = [e.path for e in results]
        assert "/ip/dhcp-server/lease/make-static" in paths


# ------------------------------------------------------------------
# Search
# ------------------------------------------------------------------


class TestApiIndexSearch:
    def test_search_firewall(self, api_index: ApiIndex) -> None:
        results = api_index.search("firewall filter")
        assert len(results) > 0
        assert results[0].path == "/ip/firewall/filter"

    def test_search_dhcp(self, api_index: ApiIndex) -> None:
        results = api_index.search("dhcp lease")
        paths = [e.path for e in results]
        assert "/ip/dhcp-server/lease" in paths

    def test_search_vlan(self, api_index: ApiIndex) -> None:
        results = api_index.search("vlan")
        paths = [e.path for e in results]
        assert "/interface/vlan" in paths

    def test_search_wifi(self, api_index: ApiIndex) -> None:
        results = api_index.search("wifi")
        paths = [e.path for e in results]
        assert "/interface/wifi" in paths

    def test_search_by_param(self, api_index: ApiIndex) -> None:
        results = api_index.search("mac-address")
        assert len(results) > 0

    def test_search_empty(self, api_index: ApiIndex) -> None:
        results = api_index.search("")
        assert results == []

    def test_search_no_match(self, api_index: ApiIndex) -> None:
        results = api_index.search("xyznotexist")
        assert results == []

    def test_search_limit(self, api_index: ApiIndex) -> None:
        results = api_index.search("interface", limit=3)
        assert len(results) <= 3

    def test_search_case_insensitive(self, api_index: ApiIndex) -> None:
        lower = api_index.search("firewall")
        upper = api_index.search("FIREWALL")
        assert [e.path for e in lower] == [e.path for e in upper]

    def test_search_hyphenated(self, api_index: ApiIndex) -> None:
        hyphen = api_index.search("dhcp-server")
        space = api_index.search("dhcp server")
        assert [e.path for e in hyphen] == [e.path for e in space]


# ------------------------------------------------------------------
# Groups summary
# ------------------------------------------------------------------


class TestGroupsSummary:
    def test_contains_major_groups(self, api_index: ApiIndex) -> None:
        summary = api_index.get_groups_summary()
        for group in ("interface", "ip", "system", "routing"):
            assert group in summary, f"Missing group: {group}"

    def test_excludes_scripting(self, api_index: ApiIndex) -> None:
        summary = api_index.get_groups_summary()
        for cmd in ("foreach", "while"):
            # These should not appear as group names.
            assert f"**{cmd}**" not in summary

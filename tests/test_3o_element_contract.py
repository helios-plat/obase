from __future__ import annotations

from obase.element_contract import ElementContract, zero_authority
from obase.sandbox_provider import FullSystemSandboxProvider


def test_element_contract_has_one_export_and_zero_authority() -> None:
    contract = ElementContract(
        element_id="test",
        element_version=1,
        owner_repo="test",
        canonical_import="test.module",
        canonical_export="Test",
        input_contract="input",
        output_contract="output",
        dependency_ports=(),
        state_model="none",
        persistence_model="none",
        authority_declaration=zero_authority(),
        async_contract="awaitable",
        failure_semantics="explicit",
        recovery_semantics="replay",
        observability_contract="visible",
        compatibility_contract="stable",
        conformance_suite=("CONTRACT",),
    )
    assert contract.authority_zero
    assert contract.to_dict()["CANONICAL_EXPORT_COUNT"] == 1


def test_full_system_sandbox_is_only_a_provider_port() -> None:
    assert getattr(FullSystemSandboxProvider, "_is_protocol", False) is True

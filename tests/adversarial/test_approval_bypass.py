"""Adversarial tests: approval gate bypass attempts.

These tests probe the approval system for bypasses and edge cases.
"""

from __future__ import annotations

import pytest

from hive.agents.approval import ApprovalPolicy
from hive.config import ApprovalConfig

# ── Approval Policy Edge Cases ───────────────────────────────────────────────


class TestApprovalPolicyAdversarial:
    """Test approval policy behavior under adversarial conditions."""

    def test_disabled_approval_bypasses_all(self):
        """When disabled, no tools should require approval."""
        from hive.tools.base import Tool

        config = ApprovalConfig(enabled=False)
        policy = ApprovalPolicy(config)

        # Create a mock tool that would normally require approval
        tool = Tool(
            name="shell_exec",
            description="Execute a shell command",
            parameters={},
            fn=lambda: None,
            requires_approval=True,
        )
        assert not policy.requires_approval(tool)

    def test_shell_exec_marked_requires_approval(self):
        """shell_exec must opt into HITL when approvals are enabled."""
        from hive.agents.approval import ApprovalPolicy
        from hive.config import ApprovalConfig
        from hive.tools.shell import ShellToolkit

        tk = ShellToolkit()
        tools = {t.name: t for t in tk.get_tools()}
        shell_tool = tools["shell_exec"]

        assert shell_tool.requires_approval is True
        assert ApprovalPolicy(ApprovalConfig(enabled=True)).requires_approval(shell_tool) is True


# ── Approval Timeout Edge Cases ──────────────────────────────────────────────


class TestApprovalTimeout:
    """Test approval timeout behavior."""

    def test_zero_timeout_means_no_expiry(self):
        """timeout_cycles=0 should mean approvals never expire."""
        config = ApprovalConfig(enabled=True, timeout_cycles=0)
        assert config.timeout_cycles == 0

    def test_negative_timeout_invalid(self):
        """Negative timeout should be rejected by config validation."""
        from pydantic import ValidationError

        with pytest.raises(ValidationError):
            ApprovalConfig(enabled=True, timeout_cycles=-1)


# ── Approval Configuration Defaults ──────────────────────────────────────────


class TestApprovalConfigDefaults:
    """Verify approval config defaults are secure."""

    def test_approval_disabled_by_default(self):
        """Approval should be disabled by default (documented risk)."""
        config = ApprovalConfig()
        assert config.enabled is False

    def test_empty_require_for_by_default(self):
        """No tools should be gated by default."""
        config = ApprovalConfig()
        assert config.require_for == []

    def test_empty_auto_approve_by_default(self):
        """No tools should be auto-approved by default."""
        config = ApprovalConfig()
        assert config.auto_approve == []

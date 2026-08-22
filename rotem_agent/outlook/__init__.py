"""Outlook desktop integration over COM.

Used instead of Microsoft Graph where an Azure AD app registration is not
available. Requires classic Outlook for Windows to be installed and signed in.
"""

from rotem_agent.outlook.com import (
    MailboxConfig,
    OutlookError,
    OutlookMailbox,
    load_mailbox_config,
    rtl_html,
)

__all__ = [
    "MailboxConfig",
    "OutlookError",
    "OutlookMailbox",
    "load_mailbox_config",
    "rtl_html",
]

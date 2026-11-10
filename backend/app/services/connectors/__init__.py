from app.services.connectors.base import BaseConnector, ConnectorError
from app.services.connectors.github_connector import GitHubConnector, github_connector
from app.services.connectors.slack_connector import SlackConnector, slack_connector
from app.services.connectors.notion_connector import NotionConnector, notion_connector


def get_connector_class(provider: str):
    p = (provider or "").lower()
    if "github" in p:
        return GitHubConnector
    if "slack" in p:
        return SlackConnector
    if "notion" in p:
        return NotionConnector
    return None


__all__ = [
    "BaseConnector",
    "ConnectorError",
    "GitHubConnector",
    "SlackConnector",
    "NotionConnector",
    "github_connector",
    "slack_connector",
    "notion_connector",
    "get_connector_class",
]


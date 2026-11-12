from app.services.connectors.base import BaseConnector, ConnectorError
from app.services.connectors.confluence_connector import ConfluenceConnector, confluence_connector
from app.services.connectors.github_connector import GitHubConnector, github_connector
from app.services.connectors.gitlab_connector import GitLabConnector, gitlab_connector
from app.services.connectors.jira_connector import JiraConnector, jira_connector
from app.services.connectors.linear_connector import LinearConnector, linear_connector
from app.services.connectors.notion_connector import NotionConnector, notion_connector
from app.services.connectors.sentry_connector import SentryConnector, sentry_connector
from app.services.connectors.slack_connector import SlackConnector, slack_connector


def get_connector_class(provider: str):
    p = (provider or "").lower()
    if "github" in p:
        return GitHubConnector
    if "slack" in p:
        return SlackConnector
    if "notion" in p:
        return NotionConnector
    if "jira" in p:
        return JiraConnector
    if "confluence" in p:
        return ConfluenceConnector
    if "linear" in p:
        return LinearConnector
    if "gitlab" in p:
        return GitLabConnector
    if "sentry" in p:
        return SentryConnector
    return None


__all__ = [
    "BaseConnector",
    "ConnectorError",
    "GitHubConnector",
    "SlackConnector",
    "NotionConnector",
    "JiraConnector",
    "ConfluenceConnector",
    "LinearConnector",
    "GitLabConnector",
    "SentryConnector",
    "github_connector",
    "slack_connector",
    "notion_connector",
    "jira_connector",
    "confluence_connector",
    "linear_connector",
    "gitlab_connector",
    "sentry_connector",
    "get_connector_class",
]


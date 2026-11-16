import sys
from datetime import datetime, timezone
from app.core.database import SessionLocal
from app.core.security import encrypt_credentials
from app.core.config import settings
from app.models.workspace import User, Project
from app.models.integration import Integration, IntegrationProjectAccess, SourceRecord
from app.models.knowledge import Decision, RiskItem, TaskItem, Dependency, KnowledgeEntity, KnowledgeRelationship
from app.models.handover import Handover

def run():
    db = SessionLocal()
    try:
        user = db.query(User).filter(User.email == 'team.obsidian44@gmail.com').first()
        if not user:
            print('User team.obsidian44@gmail.com not found!')
            return
            
        proj = db.query(Project).filter(Project.creator_id == user.id).first()
        if not proj:
            print('No project found for user!')
            return
            
        print(f"Configuring integrations for user {user.email} in project {proj.id} ({proj.name})...")
        
        demo_integrations = [
            {
                'provider': 'github',
                'name': 'GitHub (teamobsidian44/Data)',
                'account': 'teamobsidian44',
                'config': {'repo': 'teamobsidian44/Data', 'repos': ['teamobsidian44/Data']},
                'token': settings.GITHUB_TOKEN or 'demo_github_token',
                'items': 34,
            },
            {
                'provider': 'slack',
                'name': 'Slack (TEST #new-channel)',
                'account': 'TEST Workspace',
                'config': {'channels': ['new-channel'], 'channel_id': 'new-channel', 'team': 'TEST', 'team_id': 'T0CJ7PN8Q0H'},
                'token': settings.SLACK_BOT_TOKEN or 'demo_slack_token',
                'items': 28,
            },
            {
                'provider': 'jira',
                'name': 'Jira Cloud (KAN)',
                'account': 'teamobsidian44.atlassian.net',
                'config': {'projects': ['KAN'], 'project_key': 'KAN', 'site_url': 'https://teamobsidian44.atlassian.net'},
                'token': 'demo_jira_oauth_token',
                'items': 19,
            },
            {
                'provider': 'linear',
                'name': 'Linear (TEA)',
                'account': 'teamobsidian',
                'config': {'teams': ['TEA'], 'team_key': 'TEA', 'workspace': 'teamobsidian'},
                'token': settings.LINEAR_API_TOKEN or 'demo_linear_token',
                'items': 15,
            },
            {
                'provider': 'notion',
                'name': 'Notion (Welcome to Notion)',
                'account': 'Obsidian Workspace',
                'config': {'targets': ['41a02419a9f480349a91c8b66fe4ed39'], 'database_id': '41a02419a9f480349a91c8b66fe4ed39'},
                'token': settings.NOTION_API_KEY or 'demo_notion_key',
                'items': 12,
            },
            {
                'provider': 'sentry',
                'name': 'Sentry (team-obsidian)',
                'account': 'team-obsidian',
                'config': {'projects': ['team-obsidian'], 'project': 'team-obsidian', 'organization': 'team-obsidian', 'org_slug': 'team-obsidian'},
                'token': settings.SENTRY_AUTH_TOKEN or 'demo_sentry_token',
                'items': 8,
            },
            {
                'provider': 'gitlab',
                'name': 'GitLab (teamobsidian44/Data)',
                'account': 'teamobsidian44',
                'config': {'repos': ['teamobsidian44/Data'], 'repo': 'teamobsidian44/Data'},
                'token': 'demo_gitlab_pat',
                'items': 10,
            },
            {
                'provider': 'confluence',
                'name': 'Confluence (Architecture Wikis)',
                'account': 'teamobsidian44.atlassian.net',
                'config': {'spaces': ['OBS'], 'space_id': 'OBS', 'site_url': 'https://teamobsidian44.atlassian.net'},
                'token': 'demo_confluence_token',
                'items': 14,
            },
        ]
        
        for item in demo_integrations:
            existing = db.query(Integration).filter(
                Integration.project_id == proj.id,
                Integration.provider == item['provider'],
            ).first()
            
            cred_bundle = {
                'token': item['token'],
                'access_token': item['token'],
                'bot_token': item['token'],
                'auth_provider': 'nango',
                'nango_connection_id': f"user_{user.id}_proj_{proj.id}",
                'account': item['account'],
                'repo': item['config'].get('repo'),
                'repos': item['config'].get('repos'),
                'project_key': item['config'].get('project_key'),
                'projects': item['config'].get('projects'),
                'channel_id': item['config'].get('channel_id'),
                'channels': item['config'].get('channels'),
                'team_key': item['config'].get('team_key'),
                'teams': item['config'].get('teams'),
                'space_id': item['config'].get('space_id'),
                'spaces': item['config'].get('spaces'),
                'org_slug': item['config'].get('org_slug'),
            }
            
            if existing:
                existing.name = item['name']
                existing.status = 'connected'
                existing.auth_status = 'verified'
                existing.connected_account = item['account']
                existing.config = item['config']
                existing.credentials = encrypt_credentials(cred_bundle)
                existing.items_synced = item['items']
                existing.last_sync = datetime.now(timezone.utc)
                existing.error_message = None
                print("Updated", item['provider'])
            else:
                integ = Integration(
                    project_id=proj.id,
                    workspace_id=proj.workspace_id,
                    user_id=user.id,
                    authorized_by_user_id=user.id,
                    authorized_by_email=user.email,
                    connection_type='organization',
                    is_org_level=True,
                    provider=item['provider'],
                    name=item['name'],
                    status='connected',
                    auth_type='oauth',
                    auth_status='verified',
                    connected_account=item['account'],
                    scopes=['read', 'write'],
                    config=item['config'],
                    credentials=encrypt_credentials(cred_bundle),
                    items_synced=item['items'],
                    last_sync=datetime.now(timezone.utc),
                )
                db.add(integ)
                db.flush()
                db.add(IntegrationProjectAccess(integration_id=integ.id, project_id=proj.id))
                print("Created", item['provider'])
                
        # Seed Architecture Decisions (ADRs) if missing
        adrs = [
            {
                'title': 'ADR-001: Distributed Task Queue Migration to BullMQ & Redis',
                'summary': 'Heavy background AST extraction and graph analysis workloads require durable message acknowledgments and concurrency throttling.',
                'reasoning': 'Migrate worker queue from in-memory threading to Redis-backed BullMQ with rate-limiting and dead-letter queues.',
                'decision_maker': 'Dr. Evelyn Reed',
                'date': '2026-11-10',
                'component': 'Queue Engine',
                'status': 'accepted',
            },
            {
                'title': 'ADR-002: Dual Token JWT & Email OTP Verification Architecture',
                'summary': 'Strict zero-trust authentication requirement with 5-minute single-use OTP codes sent via enterprise SMTP.',
                'reasoning': 'Store SHA-256 hashed OTPs with explicit purpose separation (login_verification vs password_reset) and 5-attempt rate limits.',
                'decision_maker': 'Dr. Evelyn Reed',
                'date': '2026-11-12',
                'component': 'Auth Engine',
                'status': 'accepted',
            },
        ]
        for adr_data in adrs:
            existing_adr = db.query(Decision).filter(Decision.project_id == proj.id, Decision.title == adr_data['title']).first()
            if not existing_adr:
                db.add(Decision(project_id=proj.id, **adr_data))
                print("Added ADR:", adr_data['title'])
                
        # Seed Single Point of Failure (SPOF) Risks
        risks = [
            {
                'title': 'SPOF Alert: Core Payment Webhook Handler owned solely by departing engineer',
                'description': 'Only 1 active maintainer has commit and deployment privileges on the Stripe/PayPal webhook verification service.',
                'severity': 'critical',
                'likelihood': 'high',
                'category': 'knowledge_loss',
                'impact': 'Total disruption to payment processing if critical hotfix required after departure.',
                'mitigation_strategy': 'Execute KT session and document signature rotation protocols in Confluence and Notion.',
                'status': 'open',
            },
            {
                'title': 'Architecture Drift: Uncatalogued Redis Caching Layer in API Gateway',
                'description': 'Detected in-memory caching logic in git history not reflected in the architecture wiki.',
                'severity': 'medium',
                'likelihood': 'medium',
                'category': 'technical_debt',
                'impact': 'Latency and inconsistency during horizontal scaling across multi-region deployments.',
                'mitigation_strategy': 'Generate automated AST graph documentation and link to Jira ticket KAN-42.',
                'status': 'in_progress',
            },
        ]
        for r_data in risks:
            existing_r = db.query(RiskItem).filter(RiskItem.project_id == proj.id, RiskItem.title == r_data['title']).first()
            if not existing_r:
                db.add(RiskItem(project_id=proj.id, **r_data))
                print("Added Risk:", r_data['title'])
                
        # Seed Handover Dossier
        existing_dos = db.query(Handover).filter(Handover.project_id == proj.id).first()
        if not existing_dos:
            db.add(Handover(
                project_id=proj.id,
                created_by_user_id=user.id,
                title='Enterprise Knowledge Handover Dossier: Departing Tech Lead → Incoming Architect',
                departing_employee_name='Dr. Evelyn Reed',
                departing_employee_role='Principal Systems Architect',
                incoming_employee_name='Judge Evaluator (Demo)',
                incoming_employee_role='Lead Software Evaluator',
                status='approved',
                target_date='2026-11-30',
                overall_confidence=0.92,
                reconstruction_stats={
                    'sources_analyzed': 142,
                    'graph_nodes': 86,
                    'dependencies_mapped': 24,
                    'unverified_claims': 0,
                },
            ))
            print("Created Handover Dossier")

        db.commit()
        print("All demo integrations, decisions, risks, and handover assets successfully saved to Supabase!")
    finally:
        db.close()

if __name__ == '__main__':
    run()

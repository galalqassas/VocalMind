import asyncio
from pathlib import Path
from datetime import datetime, timezone, timedelta
import json
import random
import re

from pypdf import PdfReader
from sqlmodel import select

from app.core.security import get_password_hash
from app.models.organization import Organization
from app.models.user import User as UserModel
from app.models.enums import AgentType, UserRole
from app.models.policy import CompanyPolicy, OrganizationPolicy, PolicyCompliance
from app.models.faq import FAQArticle, OrganizationFAQArticle
from app.models.interaction import Interaction
from app.models.interaction_score import InteractionScore
from app.models.enums import ProcessingStatus
from app.models.enums import SpeakerRole
from app.models.utterance import Utterance
from app.models.transcript import Transcript
from app.core.database import engine
from app.core.config import settings
from sqlmodel.ext.asyncio.session import AsyncSession

KB_CATEGORY_PREFIX = "kb:"

NEXALINK_AGENT_PROFILES = [
    ("agent.priya@nexalink.com", "Priya"),
    ("agent.daniel@nexalink.com", "Daniel"),
    ("agent.marcus@nexalink.com", "Marcus"),
    ("agent.aisha@nexalink.com", "Aisha"),
    ("agent.hannah@nexalink.com", "Hannah"),
]


# CALL_<NN>_<agent>_<scenario>.<ext>
AUDIO_FILENAME_AGENT_PATTERN = re.compile(
    r"^CALL_\d{2}_(?P<agent>[a-zA-Z]+)_",
)


def extract_agent_token_from_filename(filename: str) -> str | None:
    """Return the lowercase agent token encoded in a CALL_<NN>_<agent>_... filename."""
    match = AUDIO_FILENAME_AGENT_PATTERN.match(Path(filename).name)
    if not match:
        return None
    return match.group("agent").lower()


def parse_nexalink_readme_mapping(readme_path: Path) -> dict[str, str]:
    """Return filename -> agent_name mapping for nexalink fixtures.

    Order of precedence:
      1) evaluation/manifest.json (canonical source of truth)
      2) Filename pattern CALL_<NN>_<agent>_<scenario>.<ext>
      3) Legacy README parsing (kept as last-resort fallback)
    """
    mapping: dict[str, str] = {}

    evaluation_manifest = readme_path.parent / "evaluation" / "manifest.json"
    if evaluation_manifest.exists():
        try:
            manifest = json.loads(evaluation_manifest.read_text(encoding="utf-8"))
            mapping.update(
                {
                    item["audio_file"]: item["primary_agent"]
                    for item in manifest.get("calls", [])
                    if item.get("audio_file") and item.get("primary_agent")
                }
            )
        except Exception as exc:
            print(f"Could not parse evaluation manifest: {exc}")

    if mapping:
        return mapping

    if readme_path.exists():
        text = readme_path.read_text(encoding="utf-8", errors="ignore")
        sections = re.split(r"\n##\s+", text)
        for section in sections:
            file_match = re.search(r"\*\*File:\*\*\s*`([^`]+)`", section)
            agent_match = re.search(r"\*\*Agent:\*\*\s*([^|\n]+)", section)
            if file_match and agent_match:
                mapping[file_match.group(1).strip()] = agent_match.group(1).strip()
        for line in text.splitlines():
            if not line.strip().startswith("| `"):
                continue
            cells = [cell.strip() for cell in line.strip().strip("|").split("|")]
            if len(cells) >= 3:
                filename = cells[0].strip("`")
                agent_name = cells[2]
                if filename and agent_name and agent_name != "-":
                    mapping.setdefault(filename, agent_name)
    return mapping


async def create_or_get_organization(session: AsyncSession, name: str, slug: str) -> Organization:
    result = await session.exec(select(Organization).where(Organization.slug == slug))
    org = result.first()
    if not org:
        org = Organization(
            name=name, 
            slug=slug,
            created_at=datetime.now(timezone.utc).replace(tzinfo=None),
            updated_at=datetime.now(timezone.utc).replace(tzinfo=None)
        )
        session.add(org)
        await session.commit()
        await session.refresh(org)
        print(f"Created organization: {name}")
    else:
        print(f"Organization already exists: {name}")
    return org


async def create_or_get_user(
    session: AsyncSession,
    org_id,
    email: str,
    name: str,
    role: UserRole,
    agent_type: AgentType | None = None,
) -> UserModel:
    result = await session.exec(select(UserModel).where(UserModel.email == email))
    user = result.first()
    if not user:
        user = UserModel(
            email=email,
            name=name,
            password_hash=get_password_hash("password123"),
            organization_id=org_id,
            role=role,
            agent_type=agent_type,
        )
        session.add(user)
        await session.commit()
        await session.refresh(user)
        print(f"Created user: {email} with role {role}")
    else:
        user.organization_id = org_id
        user.name = name
        user.role = role
        user.agent_type = agent_type
        session.add(user)
        await session.commit()
        print(f"User already exists: {email}, updated org/profile")
    return user


async def deactivate_legacy_agents(session: AsyncSession, org_id, active_agent_emails: set[str]) -> None:
    result = await session.exec(
        select(UserModel).where(
            UserModel.organization_id == org_id,
            UserModel.role == UserRole.agent,
        )
    )
    for user in result.all():
        if user.email in active_agent_emails:
            continue
        if user.is_active:
            user.is_active = False
            session.add(user)
            print(f"Deactivated legacy Nexalink agent: {user.email}")
    await session.commit()


async def seed_policies_and_faqs(session: AsyncSession, org_id):
    """Ingest policy, SOP, and KB documents into the tables used by the UI."""
    backend_dir = Path(__file__).resolve().parents[1]
    storage_docs_dir = backend_dir.parent / "storage" / "docs" / "nexalink"
    if not storage_docs_dir.exists():
        storage_docs_dir = Path("/app/storage/docs/nexalink")
    parsed_docs_dir = storage_docs_dir / "parsed-docs"
    
    if not storage_docs_dir.exists():
        print(f"Docs directory not found: {storage_docs_dir}")
        if settings.SEED_MOCK_INTERACTIONS:
            return await seed_dummy_policy(session, org_id)
        return None

    def preferred_docs(folder: Path) -> list[Path]:
        if not folder.exists():
            return []
        pdfs = sorted(folder.rglob("*.pdf"))
        if pdfs:
            return pdfs
        return sorted(
            f for f in folder.rglob("*.md")
            if not any(x in f.name for x in ["_chunks", "_raw"])
        )

    policy_files = preferred_docs(storage_docs_dir / "policy-docs")
    sop_files = preferred_docs(storage_docs_dir / "sop-procedures")
    kb_files = preferred_docs(storage_docs_dir / "knowledge-base")

    if parsed_docs_dir.exists():
        policy_files.extend(preferred_docs(parsed_docs_dir / "policies"))
        sop_files.extend(preferred_docs(parsed_docs_dir / "sops"))

    if not policy_files and not sop_files and not kb_files:
        print("No policy, SOP, or KB documents found in storage/docs/nexalink.")
        if settings.SEED_MOCK_INTERACTIONS:
            return await seed_dummy_policy(session, org_id)
        return None

    print(
        f"Found {len(policy_files)} policy docs, {len(sop_files)} SOP docs, "
        f"and {len(kb_files)} KB docs."
    )

    def read_document_text(file_path: Path) -> str:
        if file_path.suffix.lower() == ".pdf":
            try:
                reader = PdfReader(str(file_path))
                return "\n\n".join((page.extract_text() or "").strip() for page in reader.pages).strip()
            except Exception as exc:
                print(f"Error extracting PDF text from {file_path.name}: {exc}")
                return ""
        try:
            return file_path.read_text(encoding="utf-8")
        except Exception as exc:
            print(f"Error reading {file_path.name}: {exc}")
            return ""

    def extract_markdown_title(file_path: Path, text: str) -> str:
        title = file_path.stem.replace("_", " ").replace("-", " ").title()
        for line in text.splitlines():
            clean_line = line.strip()
            if clean_line.startswith("#"):
                cleaned = (
                    clean_line.lstrip("#")
                    .strip()
                    .replace("POLICY DOCUMENT:", "")
                    .replace("SOP:", "")
                    .strip()
                )
                if cleaned:
                    return cleaned.title()
        return title

    first_policy = None
    policy_count = 0
    sop_count = 0
    kb_count = 0

    for f in policy_files:
        content = read_document_text(f)
        if not content:
            continue

        title = extract_markdown_title(f, content)
        legacy_title = f.name.replace(".md", "").replace("_", " ").replace("-", " ").title()
        category = "Guidelines"

        result = await session.exec(select(CompanyPolicy).where(CompanyPolicy.policy_title == title))
        policy = result.first()
        if not policy and legacy_title != title:
            result = await session.exec(select(CompanyPolicy).where(CompanyPolicy.policy_title == legacy_title))
            policy = result.first()

        if not policy:
            policy = CompanyPolicy(
                policy_category=category,
                policy_title=title,
                policy_text=content,
                created_at=datetime.now(timezone.utc).replace(tzinfo=None),
                updated_at=datetime.now(timezone.utc).replace(tzinfo=None)
            )
            session.add(policy)
            await session.commit()
            await session.refresh(policy)
            print(f"Created policy: {title}")
        else:
            if policy.policy_title != title or policy.policy_text != content or policy.policy_category != category:
                policy.policy_title = title
                policy.policy_text = content
                policy.policy_category = category
                policy.updated_at = datetime.now(timezone.utc).replace(tzinfo=None)
                session.add(policy)
                await session.commit()
                print(f"Updated policy: {title}")

        org_pol_stmt = select(OrganizationPolicy).where(
            OrganizationPolicy.organization_id == org_id,
            OrganizationPolicy.policy_id == policy.id
        )
        org_pol_res = await session.exec(org_pol_stmt)
        if not org_pol_res.first():
            org_policy = OrganizationPolicy(organization_id=org_id, policy_id=policy.id)
            session.add(org_policy)
            await session.commit()

        if not first_policy:
            first_policy = policy
        policy_count += 1

    for f in sop_files:
        content = read_document_text(f)
        if not content:
            continue

        question = extract_markdown_title(f, content)
        legacy_question = f.name.replace(".md", "").replace("_", " ").replace("-", " ").title()
        category = "SOP"

        faq_result = await session.exec(select(FAQArticle).where(FAQArticle.question == question))
        faq = faq_result.first()
        if not faq and legacy_question != question:
            faq_result = await session.exec(select(FAQArticle).where(FAQArticle.question == legacy_question))
            faq = faq_result.first()
        if not faq:
            faq = FAQArticle(question=question, answer=content, category=category)
            session.add(faq)
            await session.commit()
            await session.refresh(faq)
            print(f"Created SOP article: {question}")
        else:
            if faq.question != question or faq.answer != content or faq.category != category:
                faq.question = question
                faq.answer = content
                faq.category = category
                faq.updated_at = datetime.now(timezone.utc).replace(tzinfo=None)
                session.add(faq)
                await session.commit()
                print(f"Updated SOP article: {question}")

        org_faq_stmt = select(OrganizationFAQArticle).where(
            OrganizationFAQArticle.organization_id == org_id,
            OrganizationFAQArticle.article_id == faq.id,
        )
        org_faq_res = await session.exec(org_faq_stmt)
        if not org_faq_res.first():
            session.add(
                OrganizationFAQArticle(
                    organization_id=org_id,
                    article_id=faq.id,
                    is_active=True,
                )
            )
            await session.commit()
        sop_count += 1

    for f in kb_files:
        content = read_document_text(f)
        if not content:
            continue

        question = extract_markdown_title(f, content)
        legacy_question = f.name.replace(".md", "").replace("_", " ").replace("-", " ").title()
        category = f"{KB_CATEGORY_PREFIX}Product & Technical Reference"

        faq_result = await session.exec(select(FAQArticle).where(FAQArticle.question == question))
        faq = faq_result.first()
        if not faq and legacy_question != question:
            faq_result = await session.exec(select(FAQArticle).where(FAQArticle.question == legacy_question))
            faq = faq_result.first()
        if not faq:
            faq = FAQArticle(question=question, answer=content, category=category)
            session.add(faq)
            await session.commit()
            await session.refresh(faq)
            print(f"Created KB article: {question}")
        else:
            if faq.question != question or faq.answer != content or faq.category != category:
                faq.question = question
                faq.answer = content
                faq.category = category
                faq.updated_at = datetime.now(timezone.utc).replace(tzinfo=None)
                session.add(faq)
                await session.commit()
                print(f"Updated KB article: {question}")

        org_faq_stmt = select(OrganizationFAQArticle).where(
            OrganizationFAQArticle.organization_id == org_id,
            OrganizationFAQArticle.article_id == faq.id,
        )
        org_faq_res = await session.exec(org_faq_stmt)
        if not org_faq_res.first():
            session.add(
                OrganizationFAQArticle(
                    organization_id=org_id,
                    article_id=faq.id,
                    is_active=True,
                )
            )
            await session.commit()
        kb_count += 1

    print(
        f"Organization {org_id} loaded {policy_count} policies, "
        f"{sop_count} SOP docs, and {kb_count} KB docs"
    )

    if not first_policy:
        if settings.SEED_MOCK_INTERACTIONS:
            return await seed_dummy_policy(session, org_id)
        return None

    return first_policy

async def seed_dummy_policy(session: AsyncSession, org_id):
    """Fallback dummy policy if real docs are missing."""
    result = await session.exec(select(CompanyPolicy).where(CompanyPolicy.policy_title == "Nexalink Refund Policy"))
    policy = result.first()
    if not policy:
        policy = CompanyPolicy(
            policy_category="Guidelines",
            policy_title="Nexalink Refund Policy",
            policy_text="Dummy policy text for testing.",
            created_at=datetime.now(timezone.utc).replace(tzinfo=None),
            updated_at=datetime.now(timezone.utc).replace(tzinfo=None)
        )
        session.add(policy)
        await session.commit()
        await session.refresh(policy)
    
    org_pol_stmt = select(OrganizationPolicy).where(
        OrganizationPolicy.organization_id == org_id,
        OrganizationPolicy.policy_id == policy.id
    )
    org_pol_res = await session.exec(org_pol_stmt)
    if not org_pol_res.first():
        org_policy = OrganizationPolicy(organization_id=org_id, policy_id=policy.id)
        session.add(org_policy)
        await session.commit()
    return policy

async def seed_interactions(
    session: AsyncSession,
    org: Organization,
    agents: list[UserModel],
    manager: UserModel,
    policy: CompanyPolicy | None,
):
    # Scan ../storage/audio/nexalink for files
    backend_dir = Path(__file__).resolve().parents[1]
    audio_dir = backend_dir.parent / "storage" / "audio" / "nexalink"
    if not audio_dir.exists():
        print(f"Audio directory not found: {audio_dir}")
        return

    audio_files = list(audio_dir.glob("*.mp3")) + list(audio_dir.glob("*.wav"))
    readme_mapping = parse_nexalink_readme_mapping(audio_dir / "README.md")

    agent_by_name = {agent.name: agent for agent in agents}
    agent_by_token = {agent.name.lower(): agent for agent in agents}
    readme_agent_to_user: dict[str, UserModel] = {
        agent_name: agent_by_name[agent_name]
        for agent_name in sorted({name for name in readme_mapping.values() if name})
        if agent_name in agent_by_name
    }

    assigned_counts = {agent.email: 0 for agent in agents}

    if not audio_files:
        print("No audio files found in storage/audio/nexalink")
        return

    print(f"Found {len(audio_files)} audio files. Creating interactions...")

    for path in audio_files:
        filename = str(Path("..") / "storage" / "audio" / "nexalink" / path.name)
        # Check if already exists
        result = await session.exec(
            select(Interaction).where(
                Interaction.organization_id == org.id,
                Interaction.audio_file_path == filename,
            )
        )
        existing_interaction = result.first()

        # 1) Prefer agent token in filename: CALL_<NN>_<agent>_<scenario>.<ext>
        # 2) Fall back to manifest/README mapping if filename lacks the token
        # 3) Last resort: deterministic hash assignment so seeding is stable
        filename_token = extract_agent_token_from_filename(path.name)
        readme_agent_name = readme_mapping.get(path.name)
        assigned_agent = (
            agent_by_token.get(filename_token)
            or readme_agent_to_user.get(readme_agent_name)
            or agents[hash(path.name) % len(agents)]
        )

        if existing_interaction:
            existing_interaction.agent_id = assigned_agent.id
            session.add(existing_interaction)
            await session.commit()
            assigned_counts[assigned_agent.email] += 1
            continue

        interaction = Interaction(
            agent_id=assigned_agent.id,
            uploaded_by=manager.id,
            organization_id=org.id,
            interaction_date=(datetime.now(timezone.utc) - timedelta(days=random.randint(0, 10))).replace(tzinfo=None),
            duration_seconds=random.randint(60, 300),
            language_detected="en",
            file_size_bytes=path.stat().st_size,
            file_format=path.suffix.lstrip(".").lower() or "wav",
            has_overlap=False,
            processing_status=ProcessingStatus.completed,
            audio_file_path=filename
        )
        session.add(interaction)
        await session.commit()
        await session.refresh(interaction)

        # Create dummy score
        score = InteractionScore(
            interaction_id=interaction.id,
            overall_score=random.uniform(0.6, 0.95),
            empathy_score=random.uniform(0.6, 1.0),
            policy_score=random.uniform(0.7, 1.0),
            resolution_score=random.uniform(0.5, 1.0),
            was_resolved=random.choice([True, False]),
            avg_response_time_seconds=random.uniform(1.0, 5.0),
            scored_at=datetime.now(timezone.utc).replace(tzinfo=None)
        )
        session.add(score)

        transcript = Transcript(
            interaction_id=interaction.id,
            full_text="Customer asked about order support; agent provided a resolution path.",
            overall_confidence=0.9,
        )
        session.add(transcript)
        await session.flush()

        # Dummy Utterance
        utt = Utterance(
            interaction_id=interaction.id,
            transcript_id=transcript.id,
            speaker_role=SpeakerRole.customer,
            start_time_seconds=0.0,
            end_time_seconds=5.0,
            text="Hello, I have a problem with my order.",
            emotion="neutral",
            emotion_confidence=0.9
        )
        session.add(utt)

        # Dummy Policy compliance
        if policy is not None:
            compliance = PolicyCompliance(
                interaction_id=interaction.id,
                policy_id=policy.id,
                is_compliant=random.choice([True, False]),
                compliance_score=random.uniform(0.3, 0.9),
                llm_reasoning="The agent adequately addressed the policy.",
                evidence_text="Agent mentioned 30 days."
            )
            session.add(compliance)
        
        await session.commit()
        assigned_counts[assigned_agent.email] += 1
        print(f"Created dummy interaction for {filename} -> {assigned_agent.name}")

    print("\nNexalink assignment summary:")
    for agent in agents:
        print(f"  {agent.email}: {assigned_counts[agent.email]} interaction(s)")


async def main():
    async with AsyncSession(engine, expire_on_commit=False) as session:
        print("Starting Database Seed for Nexalink...")
        org = await create_or_get_organization(session, "Nexalink", "nexalink")
        
        manager = await create_or_get_user(session, org.id, "manager@nexalink.com", "Nexalink Manager", UserRole.manager)
        agents = [
            await create_or_get_user(session, org.id, email, name, UserRole.agent, AgentType.human)
            for email, name in NEXALINK_AGENT_PROFILES
        ]
        await deactivate_legacy_agents(session, org.id, {email for email, _ in NEXALINK_AGENT_PROFILES})

        policy = await seed_policies_and_faqs(session, org.id)

        if settings.SEED_MOCK_INTERACTIONS:
            await seed_interactions(session, org, agents, manager, policy)
        else:
            print("Skipping mock interaction seeding (SEED_MOCK_INTERACTIONS=false).")

        print("Seeding complete! You can login with:")
        print("Manager: manager@nexalink.com / password123")
        for email, _ in NEXALINK_AGENT_PROFILES:
            print(f"Agent: {email} / password123")

if __name__ == "__main__":
    asyncio.run(main())

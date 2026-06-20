"""Seed knowledge-base content for an org from a source org + linked policies."""

from __future__ import annotations

from datetime import datetime, timezone
from uuid import UUID

from sqlmodel import select
from sqlmodel.ext.asyncio.session import AsyncSession

from app.models.faq import FAQArticle, OrganizationFAQArticle
from app.models.organization import Organization
from app.models.policy import CompanyPolicy, OrganizationPolicy

KB_CATEGORY_PREFIX = "kb:"


async def ensure_organization_knowledge_from_source(
    session: AsyncSession,
    target_organization_id: UUID,
    *,
    source_org_slug: str = "nexalink",
) -> dict[str, int]:
    """Copy SOP FAQ articles and derive KB articles for the target org."""
    source_result = await session.exec(select(Organization).where(Organization.slug == source_org_slug))
    source_org = source_result.first()
    if not source_org:
        return {"sop": 0, "kb": 0}

    sop_added = await _copy_sop_articles(session, source_org.id, target_organization_id)
    kb_added = await _ensure_kb_from_policies(session, target_organization_id)
    if sop_added or kb_added:
        await session.flush()
    return {"sop": sop_added, "kb": kb_added}


async def _copy_sop_articles(
    session: AsyncSession,
    source_org_id: UUID,
    target_org_id: UUID,
) -> int:
    source_rows = await session.exec(
        select(FAQArticle, OrganizationFAQArticle)
        .join(OrganizationFAQArticle, OrganizationFAQArticle.article_id == FAQArticle.id)
        .where(
            OrganizationFAQArticle.organization_id == source_org_id,
            OrganizationFAQArticle.is_active.is_(True),
        )
    )
    existing_questions = {
        row
        for row in (
            await session.exec(
                select(FAQArticle.question).where(FAQArticle.organization_id == target_org_id)
            )
        ).all()
    }

    added = 0
    now = datetime.now(timezone.utc).replace(tzinfo=None)
    for article, _link in source_rows.all():
        if (article.category or "").lower().startswith(KB_CATEGORY_PREFIX):
            continue
        if article.question in existing_questions:
            continue
        clone = FAQArticle(
            organization_id=target_org_id,
            question=article.question,
            answer=article.answer,
            category=article.category,
            is_active=True,
            created_at=now,
            updated_at=now,
        )
        session.add(clone)
        await session.flush()
        session.add(
            OrganizationFAQArticle(
                organization_id=target_org_id,
                article_id=clone.id,
                is_active=True,
            )
        )
        existing_questions.add(article.question)
        added += 1
    return added


async def _ensure_kb_from_policies(session: AsyncSession, target_org_id: UUID) -> int:
    policy_rows = await session.exec(
        select(CompanyPolicy)
        .join(OrganizationPolicy, OrganizationPolicy.policy_id == CompanyPolicy.id)
        .where(
            OrganizationPolicy.organization_id == target_org_id,
            OrganizationPolicy.is_active.is_(True),
            CompanyPolicy.is_active.is_(True),
        )
        .order_by(CompanyPolicy.policy_title)
    )
    policies = list(policy_rows.all())

    existing_kb_titles = {
        row
        for row in (
            await session.exec(
                select(FAQArticle.question).where(
                    FAQArticle.organization_id == target_org_id,
                    FAQArticle.category.startswith(KB_CATEGORY_PREFIX),  # type: ignore[union-attr]
                )
            )
        ).all()
    }

    added = 0
    now = datetime.now(timezone.utc).replace(tzinfo=None)
    for policy in policies:
        title = (policy.policy_title or "Policy reference").strip()
        if title in existing_kb_titles:
            continue
        excerpt = (policy.policy_text or "").strip()
        if len(excerpt) > 2400:
            excerpt = excerpt[:2400].rsplit(" ", 1)[0] + "…"
        answer = excerpt or f"Reference summary for {title}."
        faq = FAQArticle(
            organization_id=target_org_id,
            question=title,
            answer=answer,
            category=f"{KB_CATEGORY_PREFIX}{policy.policy_category or 'Guidelines'}",
            is_active=True,
            created_at=now,
            updated_at=now,
        )
        session.add(faq)
        await session.flush()
        session.add(
            OrganizationFAQArticle(
                organization_id=target_org_id,
                article_id=faq.id,
                is_active=True,
            )
        )
        existing_kb_titles.add(title)
        added += 1
    return added

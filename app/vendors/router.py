from uuid import UUID, uuid4

from fastapi import APIRouter, Depends, Query
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import get_session
from app.core.errors import DomainError
from app.identity.service import Actor, current_actor
from app.organisation.service import membership
from app.vendors.models import Vendor, VendorVersion
from app.vendors.schemas import CreateVendor, UpdateVendor, VendorPage, VendorSummary, VendorView
from app.vendors.service import add_version, require_write, scoped_vendor, view

router = APIRouter(prefix="/api/v1/vendors", tags=["Vendors"])


@router.get("", response_model=VendorPage)
async def list_vendors(
    entity_id: UUID,
    search: str = Query(default="", max_length=250),
    limit: int = Query(default=25, ge=1, le=100),
    offset: int = Query(default=0, ge=0),
    actor: Actor = Depends(current_actor),
    s: AsyncSession = Depends(get_session, scope="function"),
) -> VendorPage:
    await membership(s, actor.id, entity_id)
    query = (
        select(Vendor, VendorVersion)
        .join(VendorVersion, VendorVersion.id == Vendor.current_version_id)
        .where(Vendor.entity_id == entity_id)
    )
    if search:
        query = query.where(VendorVersion.data["name"].astext.icontains(search, autoescape=True))
    total = await s.scalar(select(func.count()).select_from(query.subquery()))
    rows = (
        await s.execute(query.order_by(Vendor.created_at, Vendor.id).offset(offset).limit(limit))
    ).all()
    return VendorPage(
        items=[
            VendorSummary(
                id=v.id,
                entity_id=v.entity_id,
                version=v.version,
                name=str(version.data["name"]),
                registration_id=str(version.data.get("registration_id", "")),
                bank_details_state="restricted" if version.beneficiary_id else "unknown",
            )
            for v, version in rows
        ],
        total=total or 0,
        limit=limit,
        offset=offset,
    )


@router.post("", response_model=VendorView, status_code=201)
async def create_vendor(
    body: CreateVendor,
    actor: Actor = Depends(current_actor),
    s: AsyncSession = Depends(get_session, scope="function"),
) -> VendorView:
    require_write(None, actor)
    await membership(s, actor.id, body.entity_id)
    vendor = Vendor(
        id=uuid4(),
        entity_id=body.entity_id,
        created_by=actor.id,
        current_version_id=uuid4(),
        version=1,
    )
    s.add(vendor)
    await s.flush()
    return await view(s, vendor, await add_version(s, vendor, body.data, actor), actor)


@router.get("/{vendor_id}", response_model=VendorView)
async def vendor_detail(
    vendor_id: UUID,
    actor: Actor = Depends(current_actor),
    s: AsyncSession = Depends(get_session, scope="function"),
) -> VendorView:
    vendor = await scoped_vendor(s, vendor_id, actor)
    version = await s.get(VendorVersion, vendor.current_version_id)
    assert version
    return await view(s, vendor, version, actor)


@router.patch("/{vendor_id}", response_model=VendorView)
async def update_vendor(
    vendor_id: UUID,
    body: UpdateVendor,
    actor: Actor = Depends(current_actor),
    s: AsyncSession = Depends(get_session, scope="function"),
) -> VendorView:
    vendor = await scoped_vendor(s, vendor_id, actor)
    require_write(vendor, actor)
    if vendor.version != body.expected_version:
        raise DomainError("REVISION_CONFLICT", "Vendor details changed. Reload before updating.")
    vendor.version += 1
    vendor.current_version_id = uuid4()
    return await view(s, vendor, await add_version(s, vendor, body.data, actor), actor)


@router.get("/{vendor_id}/versions/{number}", response_model=VendorView)
async def version_detail(
    vendor_id: UUID,
    number: int,
    actor: Actor = Depends(current_actor),
    s: AsyncSession = Depends(get_session, scope="function"),
) -> VendorView:
    vendor = await scoped_vendor(s, vendor_id, actor)
    version = await s.scalar(
        select(VendorVersion).where(
            VendorVersion.vendor_id == vendor.id, VendorVersion.number == number
        )
    )
    if not version:
        raise DomainError("RESOURCE_NOT_AVAILABLE", "Vendor version not found.", 404)
    return await view(s, vendor, version, actor)

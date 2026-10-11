"""Products and aliases. The parser worker notices catalog changes and re-parses
(human edits are kept), so nothing here writes parse results."""
from fastapi import APIRouter, Depends, Form, HTTPException, Request
from fastapi.responses import HTMLResponse, RedirectResponse
from sqlalchemy import delete, func, select
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.orm import Session

from app.models import ParseResult, Product, ProductAlias, ProductPrice
from app.parser.normalize import normalize
from app.pricing.prices import current_prices
from app.web.auth import current_user, verify_csrf
from app.web.deps import get_db, templates
from app.web.inbox import flash

router = APIRouter(prefix="/products", dependencies=[Depends(current_user), Depends(verify_csrf)])


def get_product(db: Session, product_id: int) -> Product:
    product = db.get(Product, product_id)
    if product is None:
        raise HTTPException(404, "Product not found")
    return product


@router.get("", response_class=HTMLResponse)
def products(request: Request, q: str = "", db: Session = Depends(get_db)):
    alias_count = (select(ProductAlias.product_id, func.count().label("n"))
                   .group_by(ProductAlias.product_id).subquery())
    current_count = (select(ParseResult.product_id, func.count().label("n"))
                     .where(ParseResult.is_current).group_by(ParseResult.product_id).subquery())
    query = (
        select(Product, func.coalesce(alias_count.c.n, 0), func.coalesce(current_count.c.n, 0))
        .outerjoin(alias_count, alias_count.c.product_id == Product.id)
        .outerjoin(current_count, current_count.c.product_id == Product.id)
        .order_by(Product.active.desc(), Product.brand, Product.name)
    )
    if q.strip():
        matching = select(ProductAlias.product_id).where(
            ProductAlias.normalized_alias.icontains(normalize(q), autoescape=True))
        query = query.where(
            Product.name.icontains(q.strip(), autoescape=True)
            | Product.brand.icontains(q.strip(), autoescape=True)
            | Product.id.in_(matching)
        )
    return templates.TemplateResponse(request, "products.html", {
        "rows": db.execute(query).all(), "q": q, "prices": current_prices(db)})


@router.post("")
def add_product(request: Request, brand: str = Form(...), name: str = Form(...), db: Session = Depends(get_db)):
    brand, name = brand.strip(), name.strip()
    if not brand or not name:
        raise HTTPException(400, "Brand and name are required")
    product_id = db.scalar(insert(Product).values(brand=brand, name=name, source="manual")
                           .on_conflict_do_nothing().returning(Product.id))
    if product_id is None:
        product_id = db.scalar(select(Product.id).where(Product.brand == brand, Product.name == name))
        flash(request, "That product already exists.")
    else:
        # Its own name is the first alias.
        db.execute(insert(ProductAlias).values(
            product_id=product_id, alias_text=name, normalized_alias=normalize(name), source="learned",
        ).on_conflict_do_nothing())
        flash(request, "Product added. Add the nicknames customers use below.")
    db.commit()
    return RedirectResponse(f"/products/{product_id}", status_code=303)


@router.get("/{product_id}", response_class=HTMLResponse)
def product_detail(request: Request, product_id: int, db: Session = Depends(get_db)):
    product = get_product(db, product_id)
    aliases = db.scalars(select(ProductAlias).where(ProductAlias.product_id == product_id)
                         .order_by(ProductAlias.source, ProductAlias.normalized_alias)).all()
    shared = set(db.scalars(
        select(ProductAlias.normalized_alias).where(
            ProductAlias.normalized_alias.in_([a.normalized_alias for a in aliases]),
            ProductAlias.product_id != product_id)
    ))
    history = db.scalars(select(ProductPrice).where(ProductPrice.product_id == product_id)
                         .order_by(ProductPrice.effective_from.desc(), ProductPrice.id.desc()).limit(50)).all()
    return templates.TemplateResponse(request, "product.html", {
        "product": product, "aliases": aliases, "shared": shared,
        "prices": current_prices(db, [product_id]).get(product_id, []), "history": history,
    })


@router.post("/{product_id}/active")
def set_active(request: Request, product_id: int, active: str = Form(...), db: Session = Depends(get_db)):
    product = get_product(db, product_id)
    product.active = active == "1"
    db.commit()
    flash(request, "Product activated." if product.active else
          "Product deactivated: the parser no longer matches it.")
    return RedirectResponse(f"/products/{product_id}", status_code=303)


@router.post("/{product_id}/aliases")
def add_alias(request: Request, product_id: int, alias: str = Form(...), db: Session = Depends(get_db)):
    get_product(db, product_id)
    norm = normalize(alias)
    if len(norm) < 2:
        flash(request, "Alias too short.")
    else:
        added = db.execute(insert(ProductAlias).values(
            product_id=product_id, alias_text=alias.strip(), normalized_alias=norm, source="learned",
        ).on_conflict_do_nothing()).rowcount
        db.commit()
        flash(request, "Alias added." if added else "Alias already existed.")
    return RedirectResponse(f"/products/{product_id}", status_code=303)


@router.post("/{product_id}/aliases/{alias_id}/delete")
def delete_alias(request: Request, product_id: int, alias_id: int, db: Session = Depends(get_db)):
    deleted = db.execute(delete(ProductAlias).where(
        ProductAlias.id == alias_id, ProductAlias.product_id == product_id, ProductAlias.source == "learned",
    )).rowcount
    db.commit()
    flash(request, "Alias deleted." if deleted else "Only aliases added here can be deleted; "
          "seed aliases come from data/aliases.csv.")
    return RedirectResponse(f"/products/{product_id}", status_code=303)

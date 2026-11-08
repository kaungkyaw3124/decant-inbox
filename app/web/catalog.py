"""Products and aliases. The parser worker notices catalog changes and re-parses
(human edits are kept), so nothing here writes parse results."""
from urllib.parse import urlencode

from fastapi import APIRouter, Depends, Form, HTTPException, Request
from fastapi.responses import HTMLResponse, RedirectResponse
from sqlalchemy import delete, func, select
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.orm import Session

from app.core import audit
from app.inventory import stock
from app.models import AuditLog, Bottle, ParseResult, Product, ProductAlias, ProductPrice, User, Vial
from app.parser.normalize import normalize
from app.pricing import excel
from app.pricing.prices import DEFAULT_SIZES, current_prices, latest_prices, size_sort_key
from app.web.auth import current_user, owner_only, verify_csrf
from app.web.deps import get_db, templates
from app.web.inbox import flash
from app.web import paging

router = APIRouter(prefix="/products", dependencies=[Depends(current_user), Depends(verify_csrf)])


def get_product(db: Session, product_id: int) -> Product:
    product = db.get(Product, product_id)
    if product is None:
        raise HTTPException(404, "Product not found")
    return product


TABS = ("prices", "stock", "nicks")
DIALOGS = ("add", "prices", "stock-count", "vials")  # owner only (More ▾ and + Add perfume)


def _needs_stock(db: Session) -> list[tuple[Product, str]]:
    """Counted perfumes that are low or can't be poured at all (the one warning bar)."""
    cfg, found = stock.settings(db), stock.levels(db)
    prices = current_prices(db, list(found))
    products = {p.id: p for p in db.scalars(select(Product).where(Product.id.in_(list(found)), Product.active))}
    need = []
    for pid, level in found.items():
        if pid not in products:
            continue
        if level.available_ml <= 0 or (prices.get(pid) and not any(p.in_stock for p in prices[pid])):
            need.append((products[pid], "out"))
        elif level.available_ml < stock.low_threshold(cfg, pid):
            need.append((products[pid], "low"))
    return sorted(need, key=lambda n: (n[1] != "out", n[0].name))


def _capacity(db: Session, product_ids: list[int]) -> dict[int, int]:
    """ml in the bottles that are not empty yet (the bar's 100 %)."""
    return dict(db.execute(select(Bottle.product_id, func.sum(Bottle.size_ml)).where(
        Bottle.product_id.in_(product_ids), Bottle.status != "empty").group_by(Bottle.product_id)).all())


def _here(request: Request):
    """Links that change only a few parameters of this page (None removes one); search, page and size stay."""
    def here(**changes) -> str:
        params = dict(request.query_params)
        for key, value in changes.items():
            if value is None:
                params.pop(key, None)
            else:
                params[key] = str(value)
        return "/products" + (f"?{urlencode(params)}" if params else "")
    return here


def _panel(request: Request, db: Session, product: Product) -> dict:
    """The side panel (docs/SPEC-v5.6): Prices · Stock · Nicknames for one perfume."""
    aliases = db.scalars(select(ProductAlias).where(ProductAlias.product_id == product.id)
                         .order_by(ProductAlias.source, ProductAlias.normalized_alias)).all()
    shared = set(db.scalars(select(ProductAlias.normalized_alias).where(
        ProductAlias.normalized_alias.in_([a.normalized_alias for a in aliases]), ProductAlias.product_id != product.id)))
    latest = latest_prices(db, [product.id]).get(product.id, {})
    sold = {size: p for size, p in latest.items() if p.price_mmk is not None}
    sizes = sorted({*DEFAULT_SIZES, *(s for s in sold if s is not None)})
    level = stock.levels(db, [product.id]).get(product.id)
    bottles = db.scalars(select(Bottle).where(Bottle.product_id == product.id, Bottle.status != "empty")
                         .order_by(Bottle.status, Bottle.opened_at, Bottle.id)).all()
    capacity = sum(b.size_ml for b in bottles) or 1
    tab = request.query_params.get("tab")
    return {
        "product": product, "tab": tab if tab in TABS else "prices", "aliases": aliases, "shared": shared,
        "sizes": sizes, "sold": sold, "level": level, "bottles": bottles,
        "percent": min(100, round(100 * level.available_ml / capacity)) if level else 0,
        "pour": sorted(sold.values(), key=size_sort_key),
        "available": any(p.in_stock for p in sold.values()) if sold else True,
        "changed": max((p.effective_from for p in latest.values()), default=None),
        "history": paging.paginate(db, select(ProductPrice).where(ProductPrice.product_id == product.id).order_by(
            ProductPrice.effective_from.desc(), ProductPrice.id.desc()), request, scalars=True, key="hist"),
        "n_messages": db.scalar(select(func.count()).select_from(ParseResult).where(
            ParseResult.is_current, ParseResult.product_id == product.id)),
    }


def products_page(request: Request, db: Session, user: User, dialog: str | None = None, error: str | None = None,
                  status_code: int = 200):
    """docs/SPEC-v5.6: ONE Products page — the list, the side panel (?open=<id>) and the owner's dialogs."""
    q = request.query_params.get("q", "")
    alias_count = (select(ProductAlias.product_id, func.count().label("n"))
                   .group_by(ProductAlias.product_id).subquery())
    query = (select(Product, func.coalesce(alias_count.c.n, 0))
             .outerjoin(alias_count, alias_count.c.product_id == Product.id)
             .order_by(Product.active.desc(), Product.brand, Product.name))
    if q.strip():
        matching = select(ProductAlias.product_id).where(
            ProductAlias.normalized_alias.icontains(normalize(q), autoescape=True))
        query = query.where(
            Product.name.icontains(q.strip(), autoescape=True)
            | Product.brand.icontains(q.strip(), autoescape=True)
            | Product.id.in_(matching)
        )
    need = _needs_stock(db)
    only_need = request.query_params.get("need") == "1"
    if only_need:
        query = query.where(Product.id.in_([p.id for p, _ in need]))
    page = paging.paginate(db, query, request)  # docs/SPEC-v5.4 X2
    ids = [p.id for p, _ in page.items]
    open_id = paging._number(request.query_params.get("open"))
    product = db.get(Product, open_id) if open_id else None
    dialog = dialog or request.query_params.get("dialog")
    extra = {}
    if dialog == "prices":
        extra["last_import"] = db.scalar(select(AuditLog).where(AuditLog.action == "prices.import")
                                         .order_by(AuditLog.id.desc()).limit(1))
    elif dialog == "vials":
        extra["vials"] = db.scalars(select(Vial).order_by(Vial.size_ml)).all()
    return templates.TemplateResponse(request, "products.html", {
        "page": page, "rows": page.items, "q": q, "prices": current_prices(db, ids),
        "levels": stock.levels(db, ids), "capacity": _capacity(db, ids), "need": need, "only_need": only_need,
        "need_status": dict((p.id, s) for p, s in need), "n_products": db.scalar(select(func.count()).select_from(Product)),
        "panel": _panel(request, db, product) if product else None,
        "dialog": dialog if dialog in DIALOGS and user.is_owner else None, "error": error, "here": _here(request),
        **extra,
    }, status_code=status_code)


@router.get("", response_class=HTMLResponse)
def products(request: Request, db: Session = Depends(get_db), user: User = Depends(current_user)):
    return products_page(request, db, user)


def _opened(product_id: int, tab: str = "prices") -> RedirectResponse:
    return RedirectResponse(f"/products?open={product_id}&tab={tab}", status_code=303)


def _price(value: str) -> int | None:
    value = value.replace(",", "").strip()
    if not value:
        return None
    if not value.isdigit() or not 0 < int(value) <= 100_000_000:
        raise HTTPException(400, "Prices: whole Ks only, more than 0.")
    return int(value)


@router.post("", dependencies=[Depends(owner_only)])
async def add_product(request: Request, brand: str = Form(...), name: str = Form(...), nicknames: str = Form(""),
                      db: Session = Depends(get_db), user: User = Depends(current_user)):
    brand, name = brand.strip(), name.strip()
    if not brand or not name:
        raise HTTPException(400, "Brand and name are required")
    form = await request.form()
    prices = {key.removeprefix("price_"): _price(str(v)) for key, v in form.items()
              if key.startswith("price_") and str(v).strip()}  # the dialog's 4 optional prices
    product_id = db.scalar(insert(Product).values(brand=brand, name=name, source="manual")
                           .on_conflict_do_nothing().returning(Product.id))
    if product_id is None:
        product_id = db.scalar(select(Product.id).where(Product.brand == brand, Product.name == name))
        flash(request, "That product already exists.")
    else:
        # Its own name is the first alias, then the nicknames typed in the dialog (comma separated).
        for alias in [name, *nicknames.split(",")]:
            if len(normalize(alias)) >= 2:
                db.execute(insert(ProductAlias).values(
                    product_id=product_id, alias_text=alias.strip(), normalized_alias=normalize(alias),
                    source="learned").on_conflict_do_nothing())
        if prices:
            excel.set_prices(db, db.get(Product, product_id), prices, None, user.id)
        flash(request, "Product added. Add the nicknames customers use below.")
        audit.record(db, user, "product.add", product_id=product_id, source="products page")
    db.commit()
    return RedirectResponse(f"/products/{product_id}", status_code=303)


@router.get("/{product_id}")
def product_detail(product_id: int, db: Session = Depends(get_db)):
    """The old product page is the side panel now (docs/SPEC-v5.6)."""
    get_product(db, product_id)
    return _opened(product_id)


@router.post("/{product_id}/prices", dependencies=[Depends(owner_only)])
async def save_prices(request: Request, product_id: int, db: Session = Depends(get_db),
                      user: User = Depends(current_user)):
    """The panel's Prices tab: one Save for every size; an empty box = that size is not sold."""
    product = get_product(db, product_id)
    form = await request.form()
    prices = {key.removeprefix("price_"): _price(str(v)) for key, v in form.items() if key.startswith("price_")}
    if any(k != "full" and not k.isdigit() for k in prices):
        raise HTTPException(400, "Unknown size")
    written = excel.set_prices(db, product, prices, None, user.id)
    if written:
        audit.record(db, user, "product.prices", product_id=product_id, rows=written)
    db.commit()
    flash(request, "Prices saved." if written else "No change.")
    return _opened(product_id)


@router.post("/{product_id}/available", dependencies=[Depends(owner_only)])
def set_available(request: Request, product_id: int, available: str = Form(...), db: Session = Depends(get_db),
                  user: User = Depends(current_user)):
    """Perfumes whose stock is not counted: the old manual in-stock flag, as one switch."""
    product = get_product(db, product_id)
    excel.set_prices(db, product, {}, available == "1", user.id)
    audit.record(db, user, "product.available", product_id=product_id, available=available == "1")
    db.commit()
    flash(request, "Saved: available to sell." if available == "1" else "Saved: not available to sell.")
    return _opened(product_id, "stock")


@router.post("/{product_id}/active", dependencies=[Depends(owner_only)])
def set_active(request: Request, product_id: int, active: str = Form(...), db: Session = Depends(get_db),
               user: User = Depends(current_user)):
    product = get_product(db, product_id)
    product.active = active == "1"
    audit.record(db, user, "product.activate" if product.active else "product.deactivate", product_id=product_id)
    db.commit()
    flash(request, "Product activated." if product.active else
          "Product deactivated: the parser no longer matches it.")
    return _opened(product_id)


@router.post("/{product_id}/aliases", dependencies=[Depends(owner_only)])
def add_alias(request: Request, product_id: int, alias: str = Form(...), db: Session = Depends(get_db),
              user: User = Depends(current_user)):
    get_product(db, product_id)
    norm = normalize(alias)
    if len(norm) < 2:
        flash(request, "Nickname too short.")
    else:
        added = db.execute(insert(ProductAlias).values(
            product_id=product_id, alias_text=alias.strip(), normalized_alias=norm, source="learned",
        ).on_conflict_do_nothing()).rowcount
        if added:
            audit.record(db, user, "alias.add", product_id=product_id, alias=norm)
        db.commit()
        flash(request, "Nickname added." if added else "That nickname already exists.")
    return _opened(product_id, "nicks")


@router.post("/{product_id}/aliases/{alias_id}/delete", dependencies=[Depends(owner_only)])
def delete_alias(request: Request, product_id: int, alias_id: int, db: Session = Depends(get_db),
                 user: User = Depends(current_user)):
    deleted = db.execute(delete(ProductAlias).where(
        ProductAlias.id == alias_id, ProductAlias.product_id == product_id, ProductAlias.source == "learned",
    )).rowcount
    if deleted:
        audit.record(db, user, "alias.delete", product_id=product_id, alias_id=alias_id)
    db.commit()
    flash(request, "Nickname removed." if deleted else "Only aliases added here can be deleted; "
          "seed aliases come from data/aliases.csv.")
    return _opened(product_id, "nicks")

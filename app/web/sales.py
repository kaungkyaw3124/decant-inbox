"""Sales & profit page (docs/SPEC-v3.md Step 8): date range, tiles, per day / perfume / size,
bar chart per day, .xlsx export of the same numbers."""
from urllib.parse import urlencode

from fastapi import APIRouter, Depends, Form, Request
from fastapi.responses import HTMLResponse, RedirectResponse, Response
from sqlalchemy.orm import Session

from app.models import AuditLog, User
from app.orders import sales
from app.pricing import costs
from app.web.auth import current_user, owner_only, verify_csrf
from app.web.deps import get_db, templates
from app.web.inbox import flash

router = APIRouter(prefix="/sales", dependencies=[Depends(current_user), Depends(verify_csrf)])


def _query(key: str, first, last) -> str:
    params = {"range": key}
    if key == "custom":
        params.update({"from": first.isoformat(), "to": last.isoformat()})
    return urlencode(params)


@router.get("", response_class=HTMLResponse)
def sales_page(request: Request, db: Session = Depends(get_db)):
    q = request.query_params
    key, first, last = sales.resolve(q.get("range", "today"), q.get("from", ""), q.get("to", ""))
    report = sales.report(db, key, first, last)
    return templates.TemplateResponse(request, "sales.html", {
        "r": report, "ranges": sales.RANGES, "chart": sales.chart(report), "query": _query(key, first, last),
        "missing": sales.MISSING})


@router.get("/export.xlsx")
def export(request: Request, db: Session = Depends(get_db), user: User = Depends(current_user)):
    q = request.query_params
    key, first, last = sales.resolve(q.get("range", "today"), q.get("from", ""), q.get("to", ""))
    data = sales.export(sales.report(db, key, first, last), with_costs=user.is_owner)  # staff: revenue only
    name = f"sales-{first.isoformat()}" + (f"-to-{last.isoformat()}" if last != first else "") + ".xlsx"
    return Response(data, media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
                    headers={"Content-Disposition": f'attachment; filename="{name}"'})


@router.post("/fill-costs", dependencies=[Depends(owner_only)])
def fill_costs(request: Request, range: str = Form("today"), start: str = Form("", alias="from"),
               end: str = Form("", alias="to"), db: Session = Depends(get_db), user: User = Depends(current_user)):
    """Orders paid before a bottle cost existed: use today's costs for their missing items."""
    key, first, last = sales.resolve(range, start, end)
    filled = sum(costs.stamp(db, order) for order in sales.unstamped_orders(db, first, last))
    db.add(AuditLog(user_id=user.id, action="sales.fill_costs", details={
        "from": first.isoformat(), "to": last.isoformat(), "items": filled}))
    db.commit()
    flash(request, f"Costs filled in for {filled} item(s)." if filled
          else "No costs found: add bottle_cost (and bottle size) in the price list first.")
    return RedirectResponse(f"/sales?{_query(key, first, last)}", status_code=303)

"""Turn a ranked recommendation into plain words: the dashboard's reason lines
and the SMS text. `send_sms` is a stub -- wire it to Twilio when you want real texts."""
from .config import CROP_LABEL
from .models import PHASE_LABEL


def money(x: float) -> str:
    x = round(x)
    return f"-${abs(x):,.0f}" if x < 0 else f"${x:,.0f}"


def pct(x: float) -> str:
    return f"{x:+.0%}"


def cycle_line(row) -> str:
    """One sentence on where a crop sits in its price cycle."""
    name = CROP_LABEL[row.crop]
    move = f"planted area expected {pct(row.acres_chg)}"
    price = f"price outlook ${row.exp_price:.2f}/bu ({pct(row.exp_price / row.last_price - 1)} vs last year)"
    if row.phase == "BOOM":
        return f"{name}: crowded. {move.capitalize()} after last year's price jump, so a glut is likely; {price}."
    if row.phase == "BUST":
        return f"{name}: under-planted. {move.capitalize()} after last year's price drop, so supply looks tight; {price}."
    return f"{name}: balanced. {move.capitalize()}; {price}."


def reasons(row, outlook: str) -> list[str]:
    out = [f"Typical margin {money(row.p50)}/acre; a bad year is about {money(row.p10)}, a good one {money(row.p90)}."]
    out.append(f"Market: {PHASE_LABEL[row.phase].lower()} "
               f"(planted area {pct(row.acres_chg)}, price outlook {pct(row.exp_price / row.last_price - 1)}).")
    out.append(f"Dry seasons cut its yield here by about {abs(row.yield_drop_dry):.0%}."
               if row.yield_drop_dry < -0.03 else "Its yield here holds up in dry seasons.")
    if outlook == "dry":
        out.append("Ranked with the odds tilted toward a dry season.")
    return out


def sms_text(county: str, target: int, ranked, outlook: str) -> str:
    """The text a farmer would get. Kept under ~320 characters (two SMS segments)."""
    best = ranked.iloc[0]
    crowded = ranked[ranked.phase == "BOOM"]
    parts = [f"FIELD SHIFT {county} Co. {target}:"]
    if len(crowded) and crowded.iloc[0].crop != best.crop:
        c = crowded.iloc[0]
        parts.append(f"{CROP_LABEL[c.crop]} area {pct(c.acres_chg)} after last yr's price jump, glut likely "
                     f"(${c.exp_price:.2f}/bu).")
    if outlook == "dry":
        parts.append("Dry season favoured.")
    note = " even with the crowd" if best.phase == "BOOM" else ""
    parts.append(f"Best bet{note}: {CROP_LABEL[best.crop].upper()}, about {money(best.p50)}/ac "
                 f"(bad yr {money(best.p10)}).")
    if len(ranked) > 1:
        second = ranked.iloc[1]
        parts.append(f"2nd: {CROP_LABEL[second.crop]} {money(second.p50)}/ac.")
    parts.append("Reply MORE for detail.")
    return " ".join(parts)


def send_sms(to: str, body: str) -> None:
    """Stub. With Twilio: Client(sid, token).messages.create(to=to, from_=number, body=body)."""
    print(f"[SMS to {to}] {body}")

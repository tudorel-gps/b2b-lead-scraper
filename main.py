"""LeadHarvest CLI: Google Maps -> enriched, scored B2B leads in SQLite + Excel."""

from __future__ import annotations

import argparse
import random
import sys
from datetime import datetime
from pathlib import Path

from rich.console import Console
from rich.panel import Panel
from rich.progress import BarColumn, MofNCompleteColumn, Progress, SpinnerColumn, TextColumn, TimeElapsedColumn
from rich.table import Table

from database import LeadDatabase
from enricher import COLD, HOT, WARM, enrich_leads
from exporter import export_excel, slugify
from scraper import MapsScraper, human_delay

console = Console()
TAG_STYLE = {HOT: "bold red", WARM: "yellow", COLD: "dim"}


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    p = argparse.ArgumentParser(
        prog="leadharvest",
        description="Extrage afaceri locale de pe Google Maps si le transforma in lead-uri B2B scorate.",
    )
    p.add_argument("--query", "-q", required=True, help='Nisa + locatie, ex: "clinici stomatologice Timisoara"')
    p.add_argument("--limit", "-l", type=int, default=20, help="Numar maxim de lead-uri NOI de extras (default 20)")
    p.add_argument("--visible", action="store_true", help="Porneste browserul vizibil (debugging)")
    p.add_argument("--db", default="leads.db", help="Calea bazei SQLite (default leads.db)")
    p.add_argument("--output", "-o", help="Fisier .xlsx de iesire (default exports/<query>_<timestamp>.xlsx)")
    p.add_argument("--review-threshold", type=int, default=20, help="Sub acest nr. de recenzii -> WARM_LEAD (default 20)")
    p.add_argument("--timeout", type=float, default=5.0, help="Timeout HTTP pentru verificarea site-urilor (default 5s)")
    p.add_argument("--only-new", action="store_true", help="Exporta doar lead-urile din rularea curenta (implicit: toate pentru query)")
    p.add_argument("--rotate-every", type=int, default=15, help="Schimba User-Agent-ul la fiecare N pagini (default 15)")
    args = p.parse_args(argv)
    if args.limit < 1:
        p.error("--limit trebuie sa fie >= 1")
    return args


def _progress() -> Progress:
    return Progress(
        SpinnerColumn(),
        TextColumn("[bold]{task.description}"),
        BarColumn(),
        MofNCompleteColumn(),
        TimeElapsedColumn(),
        TextColumn("{task.fields[info]}"),
        console=console,
    )


def run(args: argparse.Namespace) -> int:
    console.print(Panel.fit(f"[bold cyan]LeadHarvest[/]  ·  [white]{args.query}[/]  ·  limita {args.limit}"))
    db = LeadDatabase(args.db)
    known = db.known_keys()
    new_leads = []
    failed: list[str] = []

    try:
        with MapsScraper(headless=not args.visible) as scraper, _progress() as progress:
            # ---- Phase 1: scroll and collect place URLs
            t_collect = progress.add_task("Colectez rezultate", total=args.limit, info="")

            def on_collect(found: int, skipped: int) -> None:
                progress.update(t_collect, completed=found, info=f"[dim]{skipped} deja in baza[/]")

            urls = scraper.collect_place_urls(args.query, args.limit, skip_keys=known, on_progress=on_collect)
            progress.update(t_collect, total=max(len(urls), 1), completed=len(urls))

            if not urls:
                progress.stop()
                console.print("[yellow]Nu am gasit rezultate noi pentru aceasta cautare.[/]")
            else:
                # ---- Phase 2: visit each place
                t_detail = progress.add_task("Extrag detalii", total=len(urls), info="")
                for i, url in enumerate(urls, start=1):
                    if i > 1 and args.rotate_every and i % args.rotate_every == 0:
                        scraper.rotate_identity()
                    try:
                        lead = scraper.scrape_place(url, query=args.query)
                    except Exception as exc:  # never die mid-list
                        lead = None
                        console.log(f"[red]Eroare neasteptata:[/] {exc!r}")
                    if lead:
                        new_leads.append(lead)
                        info = lead.name[:40]
                    else:
                        failed.append(url)
                        info = "[red]esuat[/]"
                    progress.update(t_detail, advance=1, info=info)
                    human_delay(0.8, 2.2) if random.random() > 0.15 else human_delay(2.5, 4.5)
    except KeyboardInterrupt:
        console.print("\n[yellow]Intrerupt de utilizator — salvez ce am extras pana acum.[/]")
    except Exception as exc:
        console.print(f"[red]Eroare in motorul de scraping:[/] {exc!r} — continui cu datele extrase.")

    # ---- Phase 3: enrichment + scoring
    if new_leads:
        with _progress() as progress:
            t_enrich = progress.add_task("Verific website-uri", total=len(new_leads), info="")
            enrich_leads(
                new_leads,
                review_threshold=args.review_threshold,
                timeout=args.timeout,
                on_done=lambda l: progress.update(t_enrich, advance=1, info=f"{l.tag} · {l.name[:30]}"),
            )
        for lead in new_leads:
            db.upsert(lead)

    # ---- Phase 4: export
    export_set = new_leads if args.only_new else db.leads_for_query(args.query)
    db.close()

    if not export_set:
        console.print("[yellow]Nimic de exportat.[/]")
        return 1 if failed else 0

    out = Path(args.output) if args.output else Path("exports") / f"{slugify(args.query)}_{datetime.now():%Y%m%d_%H%M%S}.xlsx"
    export_excel(export_set, out)

    _print_summary(new_leads, export_set, failed, out)
    return 0


def _print_summary(new_leads, export_set, failed, out: Path) -> None:
    table = Table(title="Lead-uri noi", show_lines=False)
    for col in ("Tag", "Nume", "Rating", "Recenzii", "Telefon", "Website", "Email"):
        table.add_column(col, overflow="fold")
    for l in sorted(new_leads, key=lambda x: (x.tag != HOT, x.tag != WARM)):
        table.add_row(
            f"[{TAG_STYLE.get(l.tag, '')}]{l.tag}[/]", l.name, f"{l.rating or '-'}", f"{l.reviews if l.reviews is not None else '-'}",
            l.phone or "-", l.website if l.has_website else "[red]FARA_WEBSITE[/]", ", ".join(l.emails) or "-",
        )
    if new_leads:
        console.print(table)
    counts = {t: sum(1 for l in export_set if l.tag == t) for t in (HOT, WARM, COLD)}
    console.print(
        f"[bold green]✔[/] {len(new_leads)} noi · {len(failed)} esuate · "
        f"exportate {len(export_set)} ([red]{counts[HOT]} HOT[/] / [yellow]{counts[WARM]} WARM[/] / {counts[COLD]} COLD)"
    )
    console.print(f"[bold]Excel:[/] {out.resolve()}")


def main() -> None:
    sys.exit(run(parse_args()))


if __name__ == "__main__":
    main()

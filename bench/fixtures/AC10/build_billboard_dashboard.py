import csv
import os
import shutil
import statistics
import zipfile
from collections import Counter, defaultdict
from datetime import datetime
from xml.sax.saxutils import escape

SOURCE = "/Users/tbinns/Github/plugin-codex/bench/fixtures/AC10/billboard_top_100.csv"
OUT = "/Users/tbinns/Github/plugin-codex/bench/fixtures/AC10/.tableau_build_billboard"


def number(value):
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def ds(name, caption, filename, columns):
    relcols = "\n".join(
        f"              <column datatype='{dtype}' name='{escape(field)}' ordinal='{i}' />"
        for i, (field, dtype, role) in enumerate(columns)
    )
    metadata = "\n".join(
        f"      <column datatype='{dtype}' name='[{escape(field)}]' role='{role}' type='{'nominal' if role == 'dimension' else 'quantitative'}' />"
        for field, dtype, role in columns
    )
    return f"""    <datasource caption='{escape(caption)}' inline='true' name='{name}' version='2024.1'>
      <connection class='federated'>
        <named-connections>
          <named-connection caption='{escape(caption)}' name='textscan.{name[-6:]}'>
            <connection class='textscan' directory='Data' filename='{filename}' password='' server='' />
          </named-connection>
        </named-connections>
        <relation connection='textscan.{name[-6:]}' name='{filename}' table='[{filename.replace('.', '#')}]' type='table'>
          <columns character-set='UTF-8' header='yes' locale='en_US' separator=','>
{relcols}
          </columns>
        </relation>
      </connection>
{metadata}
    </datasource>"""


def worksheet(name, datasource, deps, rows, cols, mark, encodings="", style=""):
    depxml = "\n".join(
        f"            <column-instance column='[{escape(field)}]' derivation='{deriv}' name='[{token}]' pivot='key' type='{kind}' />"
        for field, deriv, token, kind in deps
    )
    return f"""    <worksheet name='{escape(name)}'>
      <table>
        <view>
          <datasources><datasource name='{datasource}' /></datasources>
          <datasource-dependencies datasource='{datasource}'>
{depxml}
          </datasource-dependencies>
          <aggregation value='true' />
        </view>
        <style>{style}</style>
        <panes><pane selection-relaxation-option='selection-relaxation-allow'>
          <view><breakdown value='auto' /></view>
          <mark class='{mark}' />
          <encodings>{encodings}</encodings>
        </pane></panes>
        <rows>{rows}</rows>
        <cols>{cols}</cols>
      </table>
    </worksheet>"""


os.makedirs(OUT, exist_ok=True)
data_dir = os.path.join(OUT, "Data")
os.makedirs(data_dir, exist_ok=True)

with open(SOURCE, newline="", encoding="utf-8-sig") as fh:
    rows = list(csv.DictReader(fh))

by_decade = defaultdict(lambda: {"length": [], "bpm": []})
genre_counts = defaultdict(Counter)
artist_weeks = Counter()

for row in rows:
    year = int(row["date"][:4])
    decade = year // 10 * 10
    length = number(row.get("length_sec"))
    bpm = number(row.get("bpm"))
    if length is not None:
        by_decade[decade]["length"].append(length)
    if bpm is not None:
        by_decade[decade]["bpm"].append(bpm)
    genre = (row.get("cdr_genre") or "Unknown").split(";")[0].strip() or "Unknown"
    genre_counts[decade][genre] += 1
    artist_weeks[(row.get("artist") or "Unknown").strip()] += int(float(row.get("weeks_at_number_one") or 0))

trend_path = os.path.join(data_dir, "decade_trends.csv")
with open(trend_path, "w", newline="", encoding="utf-8") as fh:
    writer = csv.writer(fh)
    writer.writerow(["Decade", "Avg Length Seconds", "Avg BPM", "Songs"])
    for decade in sorted(by_decade):
        vals = by_decade[decade]
        writer.writerow([f"{decade}s", round(statistics.mean(vals["length"]), 1), round(statistics.mean(vals["bpm"]), 1), len(vals["length"])])

top_genres = {g for g, _ in Counter({g: sum(c[g] for c in genre_counts.values()) for g in {x for c in genre_counts.values() for x in c}}).most_common(8)}
genre_path = os.path.join(data_dir, "genre_share.csv")
with open(genre_path, "w", newline="", encoding="utf-8") as fh:
    writer = csv.writer(fh)
    writer.writerow(["Decade", "Genre", "Share Percent", "Songs"])
    for decade in sorted(genre_counts):
        total = sum(genre_counts[decade].values())
        for genre in sorted(top_genres):
            count = genre_counts[decade][genre]
            writer.writerow([f"{decade}s", genre, round(100 * count / total, 1), count])

artist_path = os.path.join(data_dir, "artist_weeks.csv")
with open(artist_path, "w", newline="", encoding="utf-8") as fh:
    writer = csv.writer(fh)
    writer.writerow(["Artist", "Cumulative Weeks at #1"])
    for artist, weeks in artist_weeks.most_common(15):
        writer.writerow([artist, weeks])

trend_ds = ds("federated.trend01", "Decade Trends", "decade_trends.csv", [
    ("Decade", "string", "dimension"), ("Avg Length Seconds", "real", "measure"),
    ("Avg BPM", "real", "measure"), ("Songs", "integer", "measure")])
genre_ds = ds("federated.genre01", "Genre Share", "genre_share.csv", [
    ("Decade", "string", "dimension"), ("Genre", "string", "dimension"),
    ("Share Percent", "real", "measure"), ("Songs", "integer", "measure")])
artist_ds = ds("federated.artist1", "Artist Weeks", "artist_weeks.csv", [
    ("Artist", "string", "dimension"), ("Cumulative Weeks at #1", "integer", "measure")])

length_ws = worksheet("Song Length by Decade", "federated.trend01", [
    ("Decade", "None", "none:Decade:nk", "nominal"),
    ("Avg Length Seconds", "Avg", "avg:Avg Length Seconds:qk", "quantitative")],
    "[federated.trend01].[avg:Avg Length Seconds:qk]", "[federated.trend01].[none:Decade:nk]", "Line",
    "<color column='[federated.trend01].[avg:Avg Length Seconds:qk]' />")

bpm_ws = worksheet("BPM by Decade", "federated.trend01", [
    ("Decade", "None", "none:Decade:nk", "nominal"),
    ("Avg BPM", "Avg", "avg:Avg BPM:qk", "quantitative")],
    "[federated.trend01].[avg:Avg BPM:qk]", "[federated.trend01].[none:Decade:nk]", "Line",
    "<color column='[federated.trend01].[avg:Avg BPM:qk]' />")

genre_ws = worksheet("Genre Share Over Time", "federated.genre01", [
    ("Decade", "None", "none:Decade:nk", "nominal"), ("Genre", "None", "none:Genre:nk", "nominal"),
    ("Share Percent", "Avg", "avg:Share Percent:qk", "quantitative")],
    "[federated.genre01].[none:Genre:nk]", "[federated.genre01].[none:Decade:nk]", "Square",
    "<color column='[federated.genre01].[avg:Share Percent:qk]' /><text column='[federated.genre01].[avg:Share Percent:qk]' />")

artist_ws = worksheet("Artists with Most Weeks at #1", "federated.artist1", [
    ("Artist", "None", "none:Artist:nk", "nominal"),
    ("Cumulative Weeks at #1", "Sum", "sum:Cumulative Weeks at #1:qk", "quantitative")],
    "[federated.artist1].[none:Artist:nk]", "[federated.artist1].[sum:Cumulative Weeks at #1:qk]", "Bar",
    "<color column='[federated.artist1].[sum:Cumulative Weeks at #1:qk]' /><text column='[federated.artist1].[sum:Cumulative Weeks at #1:qk]' />")

dashboard = """    <dashboard name='Billboard #1s — Tempo, Length, Genre &amp; Staying Power'>
      <size sizing-mode='fixed' minwidth='1400' maxwidth='1400' minheight='900' maxheight='900' />
      <zones>
        <zone id='1' x='0' y='0' w='1400' h='55' type-v2='title'><layout-cache type-w='fixed' type-h='fixed' /><zone-style /></zone>
        <zone id='2' x='0' y='55' w='700' h='280' name='Song Length by Decade' type-v2='visual'><layout-cache type-w='fixed' type-h='fixed' /><zone-style /></zone>
        <zone id='3' x='700' y='55' w='700' h='280' name='BPM by Decade' type-v2='visual'><layout-cache type-w='fixed' type-h='fixed' /><zone-style /></zone>
        <zone id='4' x='0' y='335' w='850' h='565' name='Genre Share Over Time' type-v2='visual'><layout-cache type-w='fixed' type-h='fixed' /><zone-style /></zone>
        <zone id='5' x='850' y='335' w='550' h='565' name='Artists with Most Weeks at #1' type-v2='visual'><layout-cache type-w='fixed' type-h='fixed' /><zone-style /></zone>
      </zones>
    </dashboard>"""

workbook = f"""<?xml version='1.0' encoding='utf-8' ?>
<workbook original-version='2024.1' source-build='plugin-codex' source-platform='mac' version='2024.1' xmlns:user='http://www.tableausoftware.com/xml/user'>
  <document-format-change-manifest><WindowsPersistSimpleIdentifiers /></document-format-change-manifest>
  <preferences />
  <datasources>
{trend_ds}\n{genre_ds}\n{artist_ds}
  </datasources>
  <worksheets>
{length_ws}\n{bpm_ws}\n{genre_ws}\n{artist_ws}
  </worksheets>
  <dashboards>
{dashboard}
  </dashboards>
  <windows>
    <window class='dashboard' maximized='true' name='Billboard #1s — Tempo, Length, Genre &amp; Staying Power'>
      <viewpoints><viewpoint name='Song Length by Decade' /><viewpoint name='BPM by Decade' /><viewpoint name='Genre Share Over Time' /><viewpoint name='Artists with Most Weeks at #1' /></viewpoints>
      <active id='-1' />
    </window>
  </windows>
</workbook>
"""

twb_path = os.path.join(OUT, "billboard_dashboard.twb")
with open(twb_path, "w", encoding="utf-8") as fh:
    fh.write(workbook)

twbx_path = os.path.join(OUT, "billboard_dashboard.twbx")
with zipfile.ZipFile(twbx_path, "w", zipfile.ZIP_DEFLATED) as archive:
    archive.write(twb_path, "billboard_dashboard.twb")
    for filename in ("decade_trends.csv", "genre_share.csv", "artist_weeks.csv"):
        archive.write(os.path.join(data_dir, filename), f"Data/{filename}")

print(twb_path)
print(twbx_path)
print("Top artists:", artist_weeks.most_common(10))
print("Decade trends:", [(d, round(statistics.mean(v['length']), 1), round(statistics.mean(v['bpm']), 1)) for d, v in sorted(by_decade.items())])

#!/usr/bin/env python3
"""
Render site/assets/app.js against site/data/latest.json and check every table.

    python3 tools/render_check.py                    # check the current build
    python3 tools/render_check.py --verbose          # also print the panel HTML sizes
    python3 tools/render_check.py --app OLD.js --data OLD.json   # compare a variant

WHY THIS EXISTS

The dashboard's tables are assembled in JavaScript: a list of column headings
and, separately, a list of cells per row. Nothing checks the two still agree.
If they drift apart the page still renders and still looks plausible -- the
columns just silently shift, so a volatility number sits under "DD from ATH".
No Python test can catch that, because the bug only exists once the browser has
run the renderer.

This runs the renderer for real and asserts, per table, that the number of
header cells equals the number of cells in every body row.

It also catches the failure NETWORK.md records under "Deploy integrity": a
panel that renders completely empty because the JS has no handler for markup
that the HTML now carries.

HOW IT RUNS

There is no Node on this machine (`brew install node` fails on a simdjson
bottle), so this drives JavaScriptCore through `osascript -l JavaScript`
against a minimal DOM shim -- the technique NETWORK.md already describes.

Two traps, both of which cost time the first time round:
  - `main()` is async and JavaScriptCore does not drain the microtask queue
    here, so the render functions are called directly rather than via main().
  - Reading the JSON through the ObjC file bridge hands back undefined for a
    file this size. The JSON is inlined into the generated script instead,
    which is valid JavaScript as-is.

macOS-only by nature, so it is a tool rather than a test -- the CI runner is
Ubuntu and could not execute it.
"""
from __future__ import annotations

import argparse
import subprocess
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent

# Panels app.js is expected to fill. An empty one is a failure, not a warning.
PANELS = ["panel-equities", "panel-yields", "panel-macro", "panel-currencies",
          "panel-commodities", "panel-valuation", "panel-crossasset"]

SHIM = r"""
var nodes={};
function mkNode(id){return {id:id,_html:'',hidden:false,textContent:'',value:'',style:{},dataset:{},options:[],
  classList:{add:function(){},remove:function(){},toggle:function(){},contains:function(){return false}},
  get innerHTML(){return this._html}, set innerHTML(v){this._html=String(v)},
  appendChild:function(){},addEventListener:function(){},querySelector:function(){return null},
  querySelectorAll:function(){return []},getAttribute:function(){return null},setAttribute:function(){},
  closest:function(){return null},scrollIntoView:function(){},focus:function(){},remove:function(){}};}
var document={getElementById:function(id){if(!nodes[id])nodes[id]=mkNode(id);return nodes[id]},
  querySelector:function(){return null},querySelectorAll:function(){return []},
  createElement:function(){return mkNode('el')},addEventListener:function(){},body:mkNode('body')};
var window={},console={log:function(){},warn:function(){},error:function(){}};
function fetch(){return {}}
function requestAnimationFrame(){}
function getComputedStyle(){return {getPropertyValue:function(){return ''}}}
function setTimeout(){}
var localStorage={getItem:function(){return null},setItem:function(){}};
var navigator={userAgent:'jsc'};
"""

BOOT = r"""
DATA = __DATA__;
if (Array.isArray(DATA.regions) && DATA.regions.length) REGION_ORDER = DATA.regions;
renderEquities(); renderYields(); renderMacro(); renderCurrencies();
renderCommodities(); renderValuation(); renderCrossAsset();
populateRegionSelector(); renderSnapshot(REGION_ORDER[0]);

var out=[];
Object.keys(nodes).sort().forEach(function(id){
  if(id.indexOf('panel-')!==0) return;
  var h=nodes[id]._html||'';
  var tables=[];
  h.split('<table').slice(1).forEach(function(t,ti){
    var head=(t.match(/<thead>[\s\S]*?<\/thead>/)||[''])[0];
    var nH=(head.match(/<t[hd][\s>]/g)||[]).length;
    if(!nH) return;
    var body=t.replace(/<thead>[\s\S]*?<\/thead>/,'');
    var widths={};
    body.split('<tr').slice(1).forEach(function(r){
      // Chart/expander rows deliberately span the whole table.
      if(/colspan=/.test(r)) return;
      var n=(r.match(/<t[hd][\s>]/g)||[]).length;
      if(n>0) widths[n]=(widths[n]||0)+1;
    });
    tables.push({i:ti, head:nH, widths:widths});
  });
  out.push({id:id, bytes:h.length, tables:tables});
});
return JSON.stringify(out);
"""


def render(app_js: Path, data_json: Path) -> list[dict]:
    script = SHIM + "\n(function(){\n" + app_js.read_text() \
        + BOOT.replace("__DATA__", data_json.read_text()) + "\n})();"
    with tempfile.NamedTemporaryFile("w", suffix=".js", delete=False) as fh:
        fh.write(script)
        path = fh.name
    try:
        done = subprocess.run(["osascript", "-l", "JavaScript", path],
                              capture_output=True, text=True, timeout=180)
    finally:
        Path(path).unlink(missing_ok=True)
    if done.returncode != 0:
        raise RuntimeError(f"renderer failed: {done.stderr.strip()}")
    import json
    return json.loads(done.stdout.strip())


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__,
                                     formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--app", default=str(ROOT / "site" / "assets" / "app.js"))
    parser.add_argument("--data", default=str(ROOT / "site" / "data" / "latest.json"))
    parser.add_argument("--verbose", action="store_true")
    args = parser.parse_args()

    panels = render(Path(args.app), Path(args.data))
    by_id = {p["id"]: p for p in panels}
    problems = []

    for name in PANELS:
        panel = by_id.get(name)
        if panel is None or panel["bytes"] == 0:
            problems.append(f"{name}: rendered EMPTY")
            print(f"  FAIL  {name}: empty")
            continue
        bad = []
        for table in panel["tables"]:
            for width, count in table["widths"].items():
                if int(width) != table["head"]:
                    bad.append(f"table {table['i']}: {table['head']} headings "
                               f"but {count} row(s) with {width} cells")
        shape = "  ".join(
            f"t{t['i']}: {t['head']} cols x "
            f"{sum(t['widths'].values())} rows" for t in panel["tables"])
        if bad:
            problems.extend(f"{name}: {b}" for b in bad)
            print(f"  FAIL  {name}: {'; '.join(bad)}")
        else:
            print(f"  ok    {name}"
                  + (f"  ({panel['bytes']:,}B)  {shape}" if args.verbose else f"  {shape}"))

    if problems:
        print(f"\n{len(problems)} problem(s). A column heading no longer lines up "
              f"with the cells under it, or a panel rendered blank.")
        return 1
    print(f"\nAll {len(PANELS)} panels render and every column lines up.")
    return 0


if __name__ == "__main__":
    sys.exit(main())

import geopandas as gpd
import networkx as nx
import math
import os
from flask import Flask, request, jsonify, render_template_string
from shapely.geometry import Point
from shapely.ops import unary_union

# =========================
# SHAPEFILE (KESİN YOL)
# =========================
SHAPE_PATH = r"C:\onur\workspace\navigasyon\engelli.shp"

print("ÇALIŞMA DİZİNİ:", os.getcwd())
print("SHAPE PATH:", SHAPE_PATH)

gdf = gpd.read_file(SHAPE_PATH)
gdf = gdf.to_crs(epsg=3857)

print("TOPLAM GEOMETRY:", len(gdf))

network_geom = unary_union(gdf.geometry)

MAX_DIST = 15

# =========================
# GRAPH
# =========================
G = nx.Graph()

def add_line(line):
    coords = list(line.coords)
    for i in range(len(coords)-1):
        a = coords[i]
        b = coords[i+1]
        G.add_edge(a, b, weight=math.dist(a, b))

for geom in gdf.geometry:
    if geom is None:
        continue

    if geom.geom_type == "LineString":
        add_line(geom)
    elif geom.geom_type == "MultiLineString":
        for line in geom:
            add_line(line)

print("GRAPH:", len(G.nodes), "node,", len(G.edges), "edge")

# =========================
# SNAP
# =========================
def snap_to_road(p):
    point = Point(p)
    nearest_geom = network_geom.interpolate(network_geom.project(point))
    return (nearest_geom.x, nearest_geom.y)

def nearest(p):
    return min(G.nodes, key=lambda n: (n[0]-p[0])**2 + (n[1]-p[1])**2)

# =========================
# VALIDATION
# =========================
def is_valid(p):
    return network_geom.distance(Point(p)) < MAX_DIST

# =========================
# ROUTE
# =========================
def shortest_route(start, end):

    if not is_valid(start) or not is_valid(end):
        return "outside", None, None

    try:
        start_snap = snap_to_road(start)
        end_snap = snap_to_road(end)

        s = nearest(start_snap)
        e = nearest(end_snap)

        path = nx.shortest_path(G, s, e, weight="weight")

        dist = 0
        dist += math.dist(start, start_snap)

        for i in range(1, len(path)):
            dist += math.dist(path[i-1], path[i])

        dist += math.dist(end_snap, end)

        route = [start, start_snap] + path + [end_snap, end]

        return "ok", route, dist

    except Exception as e:
        print("ROUTE ERROR:", e)
        return "no_path", None, None

# =========================
# FLASK
# =========================
app = Flask(__name__)

@app.route("/route")
def route():
    sx = float(request.args.get("sx"))
    sy = float(request.args.get("sy"))
    ex = float(request.args.get("ex"))
    ey = float(request.args.get("ey"))

    status, path, dist = shortest_route((sx,sy),(ex,ey))

    return jsonify({
        "status": status,
        "path": path,
        "distance": dist
    })

@app.route("/geojson")
def geojson():
    return gdf.to_json()

@app.route("/")
def home():
    return render_template_string("""
<!DOCTYPE html>
<html>
<head>
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<link rel="stylesheet" href="https://unpkg.com/leaflet/dist/leaflet.css"/>
</head>
<body>

<h3>Engelli Navigasyon</h3>
<div id="map" style="height:600px"></div>

<script src="https://unpkg.com/leaflet/dist/leaflet.js"></script>

<script>
var map=L.map('map').setView([39.75,37.01],13);

L.tileLayer('https://{s}.tile.openstreetmap.org/{z}/{x}/{y}.png').addTo(map);

let pts=[];
let marks=[];
let line=null;

fetch("/geojson")
.then(r=>r.json())
.then(d=>{
L.geoJSON(d,{color:"red"}).addTo(map);
});

function clear(){
marks.forEach(m=>map.removeLayer(m));
marks=[];
if(line) map.removeLayer(line);
pts=[];
}

map.on('click',function(e){

marks.push(L.marker(e.latlng).addTo(map));
pts.push([e.latlng.lng,e.latlng.lat]);

if(pts.length==2){

fetch(`/route?sx=${pts[0][0]}&sy=${pts[0][1]}&ex=${pts[1][0]}&ey=${pts[1][1]}`)
.then(r=>r.json())
.then(d=>{

if(!d || !d.status){
alert("Rota bulunamadı");
clear();
return;
}

if(d.status=="outside"){
alert("🚫 Proje dışı");
clear();
return;
}

if(d.status=="no_path"){
alert("Rota bulunamadı");
clear();
return;
}

let l=d.path.map(p=>[p[1],p[0]]);

clear();

line=L.polyline(l,{color:"blue"}).addTo(map);

});
}
});
</script>

</body>
</html>
""")

# =========================
# RUN
# =========================
if __name__ == "__main__":
    app.run(host="0.0.0.0", port=5000)
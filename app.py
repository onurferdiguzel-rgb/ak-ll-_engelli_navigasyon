from flask import Flask, request, jsonify, render_template_string
from flask_cors import CORS
import geopandas as gpd
import networkx as nx
import math

app = Flask(__name__)
CORS(app)

# =====================
# SHAPEFILE
# =====================
gdf = gpd.read_file("engelli.shp")

try:
    gdf = gdf.to_crs(epsg=4326)
except:
    pass

# =====================
# GRAPH
# =====================
G = nx.Graph()

def add_line(line):
    coords = list(line.coords)
    for i in range(len(coords)-1):
        a = coords[i]
        b = coords[i+1]
        G.add_edge(a, b, weight=1)

for geom in gdf.geometry:
    if geom is None:
        continue
    if geom.geom_type == "LineString":
        add_line(geom)
    elif geom.geom_type == "MultiLineString":
        for l in geom:
            add_line(l)

# =====================
# DISTANCE
# =====================
def haversine(a, b):
    lon1, lat1 = a
    lon2, lat2 = b
    R = 6371
    dlat = math.radians(lat2-lat1)
    dlon = math.radians(lon2-lon1)
    x = math.sin(dlat/2)**2 + math.cos(math.radians(lat1))*math.cos(math.radians(lat2))*math.sin(dlon/2)**2
    return 2*R*math.asin(math.sqrt(x))

def nearest(p):
    return min(G.nodes, key=lambda n: (n[0]-p[0])**2 + (n[1]-p[1])**2)

def route(s, e):
    s = nearest(s)
    e = nearest(e)
    path = nx.shortest_path(G, s, e, weight="weight")

    dist = 0
    for i in range(1, len(path)):
        dist += haversine(path[i-1], path[i])

    return path, dist

# =====================
# API
# =====================
@app.route("/route")
def get_route():
    sx = float(request.args["sx"])
    sy = float(request.args["sy"])
    ex = float(request.args["ex"])
    ey = float(request.args["ey"])

    try:
        path, dist = route((sx,sy),(ex,ey))
        return jsonify({
            "status":"ok",
            "path":path,
            "distance":dist
        })
    except:
        return jsonify({"status":"fail"})

@app.route("/geojson")
def geojson():
    return gdf.to_json()

# =====================
# WEB MAP
# =====================
HTML = """
<!DOCTYPE html>
<html>
<head>
<link rel="stylesheet" href="https://unpkg.com/leaflet/dist/leaflet.css"/>
</head>
<body>
<div id="map" style="height:100vh"></div>

<script src="https://unpkg.com/leaflet/dist/leaflet.js"></script>
<script>
var map = L.map('map').setView([39.75,37.01],13);

L.tileLayer('https://{s}.tile.openstreetmap.org/{z}/{x}/{y}.png').addTo(map);

let points=[];
let markers=[];
let line=null;

fetch("/geojson").then(r=>r.json()).then(d=>{
    L.geoJSON(d,{color:"red"}).addTo(map);
});

map.on("click", function(e){

    markers.push(L.marker(e.latlng).addTo(map));
    points.push([e.latlng.lng, e.latlng.lat]);

    if(points.length==2){

        if(line){map.removeLayer(line)}

        fetch(`/route?sx=${points[0][0]}&sy=${points[0][1]}&ex=${points[1][0]}&ey=${points[1][1]}`)
        .then(r=>r.json())
        .then(d=>{

            if(d.status=="ok"){
                let p = d.path.map(x=>[x[1],x[0]]);
                line = L.polyline(p,{color:"blue"}).addTo(map);
                alert("Mesafe: "+d.distance.toFixed(2)+" km");
            }

        });

        points=[];
        markers.forEach(m=>map.removeLayer(m));
        markers=[];
    }

});
</script>
</body>
</html>
"""

@app.route("/")
def home():
    return render_template_string(HTML)

# =====================
# RUN
# =====================
if __name__ == "__main__":
    import os
    port = int(os.environ.get("PORT", 5000))
    app.run(host="0.0.0.0", port=port)
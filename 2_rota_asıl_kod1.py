import geopandas as gpd
import networkx as nx
import math
from flask import Flask, request, jsonify, render_template_string
from shapely.geometry import Point, LineString
from shapely.ops import unary_union
from itertools import islice

# =========================
# SHAPEFILE
# =========================
gdf = gpd.read_file("engelli.shp")

try:
    gdf = gdf.to_crs(epsg=4326)
except:
    pass

network_geom = unary_union(gdf.geometry)

# =========================
# MESAFE (METRE)
# =========================
def haversine(a, b):
    lon1, lat1 = a
    lon2, lat2 = b

    R = 6371000
    dlat = math.radians(lat2 - lat1)
    dlon = math.radians(lon2 - lon1)

    x = math.sin(dlat/2)**2 + math.cos(math.radians(lat1)) * math.cos(math.radians(lat2)) * math.sin(dlon/2)**2
    return 2 * R * math.asin(math.sqrt(x))
# =========================
# YÖN TARİFLERİ
# =========================
def bearing(a, b):

    lon1 = math.radians(a[0])
    lat1 = math.radians(a[1])

    lon2 = math.radians(b[0])
    lat2 = math.radians(b[1])

    dlon = lon2 - lon1

    x = math.sin(dlon) * math.cos(lat2)

    y = (
        math.cos(lat1) * math.sin(lat2)
        - math.sin(lat1) * math.cos(lat2) * math.cos(dlon)
    )

    brng = math.degrees(math.atan2(x, y))

    return (brng + 360) % 360

def generate_directions(path):

    if len(path) < 3:
        return ["Varış noktasına ulaştınız"]

    directions = []
    segment_dist = 0

    for i in range(1, len(path)-1):

        segment_dist += haversine(path[i-1], path[i])

        b1 = bearing(path[i-1], path[i])
        b2 = bearing(path[i], path[i+1])

        angle = b2 - b1

        while angle > 180:
            angle -= 360

        while angle < -180:
            angle += 360

        if abs(angle) > 35:

            directions.append(
                f"{round(segment_dist)} metre düz ilerle"
            )

            if angle > 0:
                directions.append("Sağa dön")
            else:
                directions.append("Sola dön")

            segment_dist = 0

    segment_dist += haversine(path[-2], path[-1])

    directions.append(
        f"{round(segment_dist)} metre düz ilerle"
    )

    directions.append("Varış noktasına ulaştınız")

    return directions

# =========================
# GRAPH
# =========================
G = nx.Graph()
edges_list = []

def add_line(line):
    coords = list(line.coords)
    for i in range(len(coords)-1):
        a = coords[i]
        b = coords[i+1]
        G.add_edge(a, b, weight=haversine(a, b))
        edges_list.append((a, b))

for geom in gdf.geometry:
    if geom is None:
        continue

    if geom.geom_type == "LineString":
        add_line(geom)
    elif geom.geom_type == "MultiLineString":
        for line in geom:
            add_line(line)

print("Graph hazır:", len(G.nodes), "node,", len(G.edges), "edge")

# =========================
# PROJE DIŞI (10m)
# =========================
MAX_DIST = 10

def is_valid(p):
    return network_geom.distance(Point(p)) * 111000 < MAX_DIST

# =========================
# SNAP + EDGE SPLIT
# =========================
def snap_and_insert(graph, p):
    point = Point(p)
    nearest_line = None
    min_dist = float("inf")

    for (a, b) in edges_list:
        line = LineString([a, b])
        d = line.distance(point)

        if d < min_dist:
            min_dist = d
            nearest_line = (a, b)

    a, b = nearest_line
    line = LineString([a, b])

    proj_point = line.interpolate(line.project(point))
    snapped = (proj_point.x, proj_point.y)

    if graph.has_edge(a, b):
        graph.remove_edge(a, b)

    graph.add_node(snapped)
    graph.add_edge(a, snapped, weight=haversine(a, snapped))
    graph.add_edge(snapped, b, weight=haversine(snapped, b))

    return snapped

def path_distance(path):
    dist = 0
    for i in range(1, len(path)):
        dist += haversine(path[i-1], path[i])
    return dist

# =========================
# ROUTE
# =========================
def shortest_routes(start, end):

    if not is_valid(start):
        return "outside", None, None, None, None, None

    if not is_valid(end):
        return "outside", None, None, None, None, None

    temp_G = G.copy()

    s_snap = snap_and_insert(temp_G, start)
    e_snap = snap_and_insert(temp_G, end)

    try:

        paths = list(
            islice(
                nx.shortest_simple_paths(
                    temp_G,
                    s_snap,
                    e_snap,
                    weight="weight"
                ),
                2
            )
        )

        path1 = paths[0]
        dist1 = path_distance(path1)
        directions1 = generate_directions(path1)

        path2 = None
        dist2 = None

        if len(paths) > 1:
            path2 = paths[1]
            dist2 = path_distance(path2)

        return "ok", path1, dist1, path2, dist2, directions1

    except:
        return "fail", None, None, None, None, None

# =========================
# FLASK
# =========================
app = Flask(__name__)

HTML = """
<!DOCTYPE html>
<html>
<head>
<link rel="stylesheet" href="https://unpkg.com/leaflet/dist/leaflet.css"/>

<style>
#map{
    height:600px;
}

/* Rota kontrol butonları */
.route-control{
    background:white;
    padding:2px;
    border-radius:4px;
    box-shadow:0 1px 3px rgba(0,0,0,0.25);
}

.route-control button{
    display:block;
    width:48px;
    padding:1px 2px;
    margin-bottom:2px;
    font-size:7px;
    cursor:pointer;
}

.route-control button:last-child{
    margin-bottom:0;
}

/* + / - zoom küçültme */
.leaflet-control-zoom{
    transform:scale(0.40);
    transform-origin:top left;
}

.leaflet-control-zoom a{
    width:18px !important;
    height:18px !important;
    line-height:18px !important;
    font-size:12px !important;
}

.leaflet-bar{
    font-size:12px !important;
}

/* popup küçültme - transform YOK, çünkü popup kayboluyordu */
.leaflet-popup-content{
    margin:1px 3px !important;
    font-size:8px !important;
    line-height:1 !important;
    min-width:90px !important;
}

.leaflet-popup-content-wrapper{
    padding:1px !important;
    border-radius:6px !important;
}

.leaflet-popup-tip{
    width:7px !important;
    height:7px !important;
}
</style>

</head>
<body>

<h3>Engelli Navigasyon Sistemi</h3>

<div id="map"></div>

<script src="https://unpkg.com/leaflet/dist/leaflet.js"></script>

<script>

var map = L.map('map').setView([39.75,37.01],13);

var RouteControl = L.Control.extend({
    options: {
        position: 'topright'
    },

    onAdd: function(map){
        var div = L.DomUtil.create('div', 'route-control');

        div.innerHTML = `
            <button onclick="toggleRoute1()">1. Rota</button>
            <button onclick="toggleRoute2()">2. Rota</button>
        `;

        L.DomEvent.disableClickPropagation(div);
        L.DomEvent.disableScrollPropagation(div);

        return div;
    }
});

map.addControl(new RouteControl());

L.tileLayer('https://{s}.tile.openstreetmap.org/{z}/{x}/{y}.png').addTo(map);

let pts = [];
let markers = [];
let line1 = null;
let line2 = null;
let popup = null;

let lastRoute1 = null;
let lastRoute2 = null;
let route1Visible = true;
let route2Visible = true;

fetch("/geojson")
.then(r=>r.json())
.then(d=>{
    L.geoJSON(d,{
        color:"red",
        weight:1,
        opacity:0.8
    }).addTo(map);
});

function clearAll(){
    markers.forEach(m => map.removeLayer(m));
    markers = [];

    if(line1){
        map.removeLayer(line1);
        line1 = null;
    }

    if(line2){
        map.removeLayer(line2);
        line2 = null;
    }

    if(popup){
        map.closePopup();
        popup = null;
    }

    lastRoute1 = null;
    lastRoute2 = null;
    route1Visible = true;
    route2Visible = true;

    pts = [];
}

function toggleRoute1(){
    if(!lastRoute1) return;

    if(route1Visible){
        if(line1){
            map.removeLayer(line1);
            line1 = null;
        }
        route1Visible = false;
    } else {
        line1 = L.polyline(lastRoute1,{
            color:"blue",
            weight:3
        }).addTo(map);
        route1Visible = true;
    }
}

function toggleRoute2(){
    if(!lastRoute2) return;

    if(route2Visible){
        if(line2){
            map.removeLayer(line2);
            line2 = null;
        }
        route2Visible = false;
    } else {
        line2 = L.polyline(lastRoute2,{
            color:"green",
            weight:2,
            dashArray:"8,8"
        }).addTo(map);
        route2Visible = true;
    }
}

map.on('click', function(e){

    let p = [e.latlng.lng, e.latlng.lat];

    markers.push(L.marker(e.latlng).addTo(map));
    pts.push(p);

    if(pts.length == 2){

        fetch(`/route?sx=${pts[0][0]}&sy=${pts[0][1]}&ex=${pts[1][0]}&ey=${pts[1][1]}`)
        .then(r=>r.json())
        .then(d=>{

            if(d.status=="outside"){
                alert("🚫 Proje dışı (10 metre)");
                clearAll();
                return;
            }

            if(d.status!="ok"){
                alert("Rota bulunamadı");
                clearAll();
                return;
            }

            let l1 = d.path.map(p=>[p[1],p[0]]);

            clearAll();

            lastRoute1 = l1;
            route1Visible = true;

            line1 = L.polyline(l1,{
                color:"blue",
                weight:3
            }).addTo(map);

            let popupText = "1. rota: " + Math.round(d.distance) + " metre";

            if(d.path2){
                let l2 = d.path2.map(p=>[p[1],p[0]]);

                lastRoute2 = l2;
                route2Visible = true;

                line2 = L.polyline(l2,{
                    color:"green",
                    weight:2,
                    dashArray:"8,8"
                }).addTo(map);

                popupText += "<br>2. rota: " + Math.round(d.distance2) + " metre";
            } else {
                popupText += "<br>2. rota bulunamadı";
            }
                popupText += "<hr>";

if(d.directions){

    d.directions.forEach(function(x){
        popupText += x + "<br>";
    });

}

            popup = L.popup({
                maxWidth:90,
                minWidth:40,
                autoPan:true
            })
            .setLatLng(l1[Math.floor(l1.length/2)])
            .setContent(popupText)
            .openOn(map);

        });

    }

});

</script>

</body>
</html>
"""

@app.route("/")
def home():
    return render_template_string(HTML)

@app.route("/route")
def route():

    sx = float(request.args.get("sx"))
    sy = float(request.args.get("sy"))
    ex = float(request.args.get("ex"))
    ey = float(request.args.get("ey"))

    status, path1, dist1, path2, dist2, directions = shortest_routes(
        (sx, sy),
        (ex, ey)
    )

    return jsonify({
        "status": status,
        "path": path1,
        "distance": dist1,
        "path2": path2,
        "distance2": dist2,
        "directions": directions
    })

@app.route("/geojson")
def geojson():
    return gdf.to_json()

if __name__ == "__main__":
    app.run(host="0.0.0.0", port=5000)
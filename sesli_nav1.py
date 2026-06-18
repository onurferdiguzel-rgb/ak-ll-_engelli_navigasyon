# -*- coding: utf-8 -*-
"""
Created on Thu Jun 18 15:40:30 2026

@author: acer
"""

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

noktalar_gdf = gpd.read_file("noktalar.shp")
try:
    noktalar_gdf = noktalar_gdf.to_crs(epsg=4326)
except:
    pass

network_geom = unary_union(gdf.geometry)

# =========================
# MESAFE
# =========================
def haversine(a, b):
    lon1, lat1 = a
    lon2, lat2 = b
    R = 6371000

    dlat = math.radians(lat2 - lat1)
    dlon = math.radians(lon2 - lon1)

    x = (
        math.sin(dlat / 2) ** 2
        + math.cos(math.radians(lat1))
        * math.cos(math.radians(lat2))
        * math.sin(dlon / 2) ** 2
    )

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


def compass_direction(angle):
    dirs = [
        "Kuzey",
        "Kuzeydoğu",
        "Doğu",
        "Güneydoğu",
        "Güney",
        "Güneybatı",
        "Batı",
        "Kuzeybatı",
    ]

    return dirs[round(angle / 45) % 8]


def generate_directions(path):
    if len(path) < 2:
        return ["Varış noktasına ulaştınız"]

    directions = []

    first_bearing = bearing(path[0], path[1])
    directions.append(f"{compass_direction(first_bearing)} yönünde ilerleyin")

    if len(path) < 3:
        directions.append("Varış noktasına ulaştınız")
        return directions

    segment_dist = 0

    for i in range(1, len(path) - 1):
        segment_dist += haversine(path[i - 1], path[i])

        b1 = bearing(path[i - 1], path[i])
        b2 = bearing(path[i], path[i + 1])

        angle = b2 - b1

        while angle > 180:
            angle -= 360

        while angle < -180:
            angle += 360

        if abs(angle) > 35:
            directions.append(f"{round(segment_dist)} metre düz ilerle")

            if angle > 0:
                directions.append("Sağa dön")
            else:
                directions.append("Sola dön")

            segment_dist = 0

    segment_dist += haversine(path[-2], path[-1])
    directions.append(f"{round(segment_dist)} metre düz ilerle")
    directions.append("Varış noktasına ulaştınız")

    return directions

# =========================
# GRAPH
# =========================
G = nx.Graph()
edges_list = []

def add_line(line):
    coords = list(line.coords)

    for i in range(len(coords) - 1):
        a = coords[i]
        b = coords[i + 1]

        G.add_edge(a, b, weight=haversine(a, b))
        edges_list.append((a, b))

for geom in gdf.geometry:
    if geom is None:
        continue

    if geom.geom_type == "LineString":
        add_line(geom)

    elif geom.geom_type == "MultiLineString":
        for line in geom.geoms:
            add_line(line)

print("Graph hazır:", len(G.nodes), "node,", len(G.edges), "edge")

# =========================
# PROJE DIŞI
# =========================
MAX_DIST = 10

def is_valid(p):
    return network_geom.distance(Point(p)) * 111000 < MAX_DIST

# =========================
# SNAP
# =========================
def snap_and_insert(graph, p):
    point = Point(p)
    nearest_line = None
    min_dist = float("inf")

    for a, b in edges_list:
        line = LineString([a, b])
        d = line.distance(point)

        if d < min_dist:
            min_dist = d
            nearest_line = (a, b)

    if nearest_line is None:
        return None

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
        dist += haversine(path[i - 1], path[i])

    return dist


def get_two_routes(start, end):
    if not is_valid(start):
        return []

    if not is_valid(end):
        return []

    temp_G = G.copy()

    s_snap = snap_and_insert(temp_G, start)
    e_snap = snap_and_insert(temp_G, end)

    if s_snap is None or e_snap is None:
        return []

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

        results = []

        for p in paths:
            dist = path_distance(p)
            results.append({
                "path": p,
                "distance": dist,
                "directions": generate_directions(p)
            })

        return results

    except:
        return []

# =========================
# GİRİŞ NOKTASI ADI
# =========================
def get_entry_name(row):
    for col in ["ADI", "adi", "Ad", "ad", "NAME", "name"]:
        if col in noktalar_gdf.columns:
            return str(row[col])

    return "Giriş noktası"

# =========================
# AKILLI ROTA
# =========================
def smart_routes(user_point, target_point):

    if not is_valid(target_point):
        return {
            "status": "outside_target",
            "routes": []
        }

    # Kullanıcı zaten engelli ağı üzerindeyse
    if is_valid(user_point):
        direct_routes = get_two_routes(user_point, target_point)

        routes = []

        for r in direct_routes:
            routes.append({
                "mode": "walk_only",
                "entry": None,
                "entry_name": None,
                "access_distance": 0,
                "walk_distance": r["distance"],
                "total_distance": r["distance"],
                "walk_path": r["path"],
                "directions": r["directions"]
            })

        if len(routes) == 0:
            return {
                "status": "fail",
                "routes": []
            }

        return {
            "status": "ok",
            "routes": routes[:2]
        }

    # Kullanıcı engelli ağı dışındaysa: tüm giriş noktalarını dene
    candidates = []

    for idx, row in noktalar_gdf.iterrows():
        geom = row.geometry

        if geom is None:
            continue

        entry_point = (geom.x, geom.y)

        # Giriş noktası gerçekten ağ üzerinde/çok yakın mı?
        if not is_valid(entry_point):
            continue

        entry_routes = get_two_routes(entry_point, target_point)

        if len(entry_routes) == 0:
            continue

        access_dist = haversine(user_point, entry_point)
        entry_name = get_entry_name(row)

        for r in entry_routes:
            total = access_dist + r["distance"]

            directions = []
            directions.append(
                f"Araç rotasıyla {round(access_dist)} metre ilerleyin"
            )
            directions.append(
                f"{entry_name} geçiş noktasına ulaştığınızda erişilebilir yaya ağına geçin"
            )
            directions.extend(r["directions"])

            candidates.append({
                "mode": "car_plus_walk",
                "entry": {
                    "x": entry_point[0],
                    "y": entry_point[1],
                    "name": entry_name
                },
                "entry_name": entry_name,
                "access_distance": access_dist,
                "walk_distance": r["distance"],
                "total_distance": total,
                "walk_path": r["path"],
                "directions": directions
            })

    if len(candidates) == 0:
        return {
            "status": "fail",
            "routes": []
        }

    candidates.sort(key=lambda x: x["total_distance"])

    return {
        "status": "ok",
        "routes": candidates[:2]
    }

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

.route-control{
    background:white;
    padding:4px;
    border-radius:6px;
    box-shadow:0 1px 4px rgba(0,0,0,0.35);
}

.route-control button{
    display:block;
    width:95px;
    padding:4px;
    margin-bottom:4px;
    font-size:12px;
    cursor:pointer;
}

.route-control button:last-child{
    margin-bottom:0;
}

.result-control{
    background:white;
    width:250px;
    max-height:360px;
    overflow-y:auto;
    padding:10px;
    border-radius:10px;
    box-shadow:0 1px 5px rgba(0,0,0,0.4);
    font-family:Arial;
    font-size:12px;
    display:none;
}

.result-title{
    font-weight:bold;
    margin-bottom:6px;
    border-bottom:1px solid #ccc;
    padding-bottom:4px;
}

.voice-btn{
    font-size:11px;
    padding:4px 7px;
    border:1px solid #bbb;
    border-radius:6px;
    background:#f7f7f7;
    cursor:pointer;
    margin:0;
}

.stop-btn{
    background:#fff3f3;
}

.leaflet-control-zoom{
    transform:scale(0.75);
    transform-origin:top left;
}
</style>
</head>

<body>

<h3>Akıllı Engelli Navigasyon Sistemi</h3>
<div id="map"></div>

<script src="https://unpkg.com/leaflet/dist/leaflet.js"></script>

<script>

let userLocation = null;
let targetMarker = null;
let userMarker = null;
let shpBounds = null;

let routeLayers = [null, null];
let selectedRouteIndex = 0;
let currentDirectionsList = [];
let routeData = [];

function speak(text){
    if('speechSynthesis' in window){
        speechSynthesis.cancel();

        let msg = new SpeechSynthesisUtterance(text);
        msg.lang = "tr-TR";
        msg.rate = 0.95;
        msg.pitch = 1.0;

        speechSynthesis.speak(msg);
    }
}

function stopSpeak(){
    if('speechSynthesis' in window){
        speechSynthesis.cancel();
    }
}

function speakSelectedRoute(){
    if(currentDirectionsList.length == 0){
        return;
    }

    stopSpeak();

    let i = 0;

    function next(){
        if(i >= currentDirectionsList.length){
            return;
        }

        let msg = new SpeechSynthesisUtterance(currentDirectionsList[i]);
        msg.lang = "tr-TR";
        msg.rate = 0.9;

        msg.onend = function(){
            i++;
            setTimeout(next, 2200);
        };

        speechSynthesis.speak(msg);
    }

    next();
}

var map = L.map('map').setView([39.709,37.034],15);

L.tileLayer('https://{s}.tile.openstreetmap.org/{z}/{x}/{y}.png').addTo(map);

var RouteControl = L.Control.extend({
    options:{position:'topright'},

    onAdd:function(map){
        var div = L.DomUtil.create('div','route-control');

        div.innerHTML = `
            <button onclick="getMyLocation()">Konumum</button>
            <button onclick="zoomToShp()">Zoom</button>
            <button onclick="selectRoute(0)">1. Rota</button>
            <button onclick="selectRoute(1)">2. Rota</button>
        `;

        L.DomEvent.disableClickPropagation(div);
        L.DomEvent.disableScrollPropagation(div);

        return div;
    }
});

map.addControl(new RouteControl());

var ResultControl = L.Control.extend({
    options:{position:'topright'},

    onAdd:function(map){
        var div = L.DomUtil.create('div','result-control');
        div.id = "resultPanel";

        div.innerHTML = `
            <div class="result-title">SONUÇLAR</div>
            <div id="resultContent"></div>
        `;

        L.DomEvent.disableClickPropagation(div);
        L.DomEvent.disableScrollPropagation(div);

        return div;
    }
});

map.addControl(new ResultControl());

let resultPanel = document.getElementById("resultPanel");
let resultContent = document.getElementById("resultContent");

fetch("/geojson")
.then(r=>r.json())
.then(d=>{

    let shpLayer = L.geoJSON(d,{
        color:"red",
        weight:1.5,
        opacity:0.85
    }).addTo(map);

    shpBounds = shpLayer.getBounds();
    map.fitBounds(shpBounds);
});

fetch("/entries_geojson")
.then(r=>r.json())
.then(d=>{
    L.geoJSON(d,{
        pointToLayer:function(feature, latlng){
            return L.circleMarker(latlng,{
                radius:4,
                color:"black",
                fillColor:"yellow",
                fillOpacity:1,
                weight:1
            });
        }
    }).addTo(map);
});

function zoomToShp(){
    if(shpBounds){
        map.fitBounds(shpBounds);
    }
}

function getMyLocation(){
    if(!navigator.geolocation){
        alert("Tarayıcı konum desteklemiyor.");
        return;
    }

    navigator.geolocation.getCurrentPosition(function(pos){

        let lat = pos.coords.latitude;
        let lng = pos.coords.longitude;

        userLocation = [lng, lat];

        if(userMarker){
            map.removeLayer(userMarker);
        }

        userMarker = L.marker([lat,lng]).addTo(map)
            .bindPopup("Canlı konum").openPopup();

        resultContent.innerHTML =
            "<b>Canlı konum alındı.</b><br>Şimdi hedef noktayı seçin.";

        resultPanel.style.display = "block";

        map.setView([lat,lng],16);

    }, function(){
        alert("Konum alınamadı. Tarayıcıdan izin verin.");
    });
}

function clearRoutes(){
    for(let i=0;i<2;i++){
        if(routeLayers[i]){
            map.removeLayer(routeLayers[i]);
            routeLayers[i] = null;
        }
    }

    currentDirectionsList = [];
}

function selectRoute(index){

    selectedRouteIndex = index;

    for(let i=0;i<2;i++){

        if(routeLayers[i]){

            if(i == index){
                routeLayers[i].addTo(map);
            }else{
                map.removeLayer(routeLayers[i]);
            }

        }
    }

    if(routeData[index]){
        currentDirectionsList = routeData[index].directions;
    }
}

function drawOSRM(userLng, userLat, entryX, entryY, group, callback){

    fetch(`https://router.project-osrm.org/route/v1/driving/${userLng},${userLat};${entryX},${entryY}?overview=full&geometries=geojson`)
    .then(r=>r.json())
    .then(osrm=>{

        if(osrm.routes && osrm.routes.length > 0){

            let coords = osrm.routes[0].geometry.coordinates;
            let roadLine = coords.map(c => [c[1], c[0]]);

            L.polyline(roadLine,{
                color:"orange",
                weight:3
            }).addTo(group);

        }else{

            L.polyline([
                [userLat,userLng],
                [entryY,entryX]
            ],{
                color:"orange",
                weight:3
            }).addTo(group);
        }

        callback();
    })
    .catch(()=>{
        L.polyline([
            [userLat,userLng],
            [entryY,entryX]
        ],{
            color:"orange",
            weight:3
        }).addTo(group);

        callback();
    });
}

function drawRoutes(data){

    clearRoutes();

    if(!data.routes || data.routes.length == 0){
        alert("Rota bulunamadı.");
        return;
    }
    routeData = data.routes;

    let html = "";

    data.routes.forEach(function(route, index){

        let group = L.layerGroup();

        let color = index == 0 ? "blue" : "green";

        let walkLine = route.walk_path.map(p=>[p[1],p[0]]);

        if(route.mode == "car_plus_walk" && route.entry){

            drawOSRM(
                userLocation[0],
                userLocation[1],
                route.entry.x,
                route.entry.y,
                group,
                function(){}
            );

            L.circleMarker([route.entry.y, route.entry.x],{
                radius:5,
                color:"black",
                fillColor:"orange",
                fillOpacity:1
            }).addTo(group);
        }

        L.polyline(walkLine,{
            color:color,
            weight:3
        }).addTo(group);

        routeLayers[index] = group;

        if(index == 0){
            group.addTo(map);
            currentDirectionsList = route.directions;
        }

        html += "<b>" + (index+1) + ". rota</b><br>";

        if(route.mode == "car_plus_walk"){
            html += "Geçiş: " + route.entry_name + "<br>";
            html += "Araç: " + Math.round(route.access_distance) + " m<br>";
        }else{
            html += "Doğrudan erişilebilir ağ<br>";
        }

        html += "Yaya: " + Math.round(route.walk_distance) + " m<br>";
        html += "Toplam: " + Math.round(route.total_distance) + " m<br><br>";
    });

    html += "<hr>";
    html += "<div style='display:flex;gap:5px;margin-bottom:8px;'>";
    html += "<button class='voice-btn' onclick='speakSelectedRoute()'>🔊 Sesli Oku</button>";
    html += "<button class='voice-btn stop-btn' onclick='stopSpeak()'>⏹ Durdur</button>";
    html += "</div>";

    html += "<b>Talimatlar:</b><br>";

    if(currentDirectionsList){
        currentDirectionsList.forEach(function(x){
            html += "• " + x + "<br>";
        });
    }

    resultContent.innerHTML = html;
    resultPanel.style.display = "block";
}

map.on('click', function(e){

    if(!userLocation){
        alert("Önce Konumum butonuna basın.");
        return;
    }

    let target = [e.latlng.lng, e.latlng.lat];

    if(targetMarker){
        map.removeLayer(targetMarker);
    }

    targetMarker = L.marker(e.latlng).addTo(map)
        .bindPopup("Hedef").openPopup();

    fetch(`/smart_route?ux=${userLocation[0]}&uy=${userLocation[1]}&tx=${target[0]}&ty=${target[1]}`)
    .then(r=>r.json())
    .then(d=>{

        if(d.status == "outside_target"){
            alert("Hedef erişilebilir ağ dışında.");
            return;
        }

        if(d.status != "ok"){
            alert("Rota bulunamadı.");
            return;
        }

        drawRoutes(d);
    });
});

</script>

</body>
</html>
"""

@app.route("/")
def home():
    return render_template_string(HTML)

@app.route("/smart_route")
def smart_route():
    ux = float(request.args.get("ux"))
    uy = float(request.args.get("uy"))
    tx = float(request.args.get("tx"))
    ty = float(request.args.get("ty"))

    result = smart_routes(
        (ux, uy),
        (tx, ty)
    )

    return jsonify(result)

@app.route("/geojson")
def geojson():
    return gdf.to_json()

@app.route("/entries_geojson")
def entries_geojson():
    return noktalar_gdf.to_json()

if __name__ == "__main__":
    app.run(host="0.0.0.0", port=5000)
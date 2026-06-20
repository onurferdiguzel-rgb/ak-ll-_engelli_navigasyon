# -*- coding: utf-8 -*-
"""
Akıllı Engelli Navigasyon Sistemi
engelli.shp + noktalar.shp
Canlı konum, en iyi 2 rota, rota seçimi, sesli okuma ve canlı takip.
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


def turn_text_from_angle(angle):
    abs_angle = abs(angle)

    if angle > 0:
        if abs_angle < 45:
            return "Hafif sağa yönelin", "20 metre sonra hafif sağa yönelin"
        elif abs_angle < 120:
            return "Sağa dönün", "20 metre sonra sağa dönün"
        else:
            return "Keskin sağa dönün", "20 metre sonra keskin sağa dönün"

    else:
        if abs_angle < 45:
            return "Hafif sola yönelin", "20 metre sonra hafif sola yönelin"
        elif abs_angle < 120:
            return "Sola dönün", "20 metre sonra sola dönün"
        else:
            return "Keskin sola dönün", "20 metre sonra keskin sola dönün"


def generate_direction_info(path):

    if len(path) < 2:
        return ["Varış noktasına ulaştınız"], []

    directions = []
    walk_steps = []

    first_bearing = bearing(path[0], path[1])
    first_text = f"{compass_direction(first_bearing)} yönünde ilerleyin"

    directions.append(first_text)

    walk_steps.append({
        "x": path[0][0],
        "y": path[0][1],
        "text": first_text,
        "threshold": 999
    })

    if len(path) < 3:
        directions.append("Varış noktasına ulaştınız")
        walk_steps.append({
            "x": path[-1][0],
            "y": path[-1][1],
            "text": "Varış noktasına ulaştınız",
            "threshold": 8
        })
        return directions, walk_steps

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

        if abs(angle) > 20:

            directions.append(f"{round(segment_dist)} metre düz ilerle")

            turn_text, live_text = turn_text_from_angle(angle)

            directions.append(turn_text)

            walk_steps.append({
                "x": path[i][0],
                "y": path[i][1],
                "text": live_text,
                "threshold": 20
            })

            segment_dist = 0

    segment_dist += haversine(path[-2], path[-1])

    directions.append(f"{round(segment_dist)} metre düz ilerle")
    directions.append("Varış noktasına ulaştınız")

    walk_steps.append({
        "x": path[-1][0],
        "y": path[-1][1],
        "text": "Varış noktasına ulaştınız",
        "threshold": 8
    })

    return directions, walk_steps

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
            directions, walk_steps = generate_direction_info(p)

            results.append({
                "path": p,
                "distance": dist,
                "directions": directions,
                "walk_steps": walk_steps
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

    # Kullanıcı zaten engelli ağı üzerindeyse: doğrudan yaya modu
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
                "directions": r["directions"],
                "walk_steps": r["walk_steps"]
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

        # Giriş noktası gerçekten erişilebilir ağa yakın mı?
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
                f"Araç rotasıyla yaklaşık {round(access_dist)} metre ilerleyin"
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
                "directions": directions,
                "walk_steps": r["walk_steps"]
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
<meta name="viewport" content="width=device-width, initial-scale=1.0">

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
    width:105px;
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
    width:270px;
    max-height:60vh;
    overflow:hidden;
    padding:10px;
    border-radius:10px;
    box-shadow:0 1px 5px rgba(0,0,0,0.4);
    font-family:Arial;
    font-size:12px;
    display:none;
}

#resultContent{
    height:320px;
    overflow-y:scroll;
    overflow-x:hidden;
    padding-right:4px;
    border-top:1px solid #ddd;
}


.result-header{
    position:sticky;
    top:0;
    background:white;
    z-index:999;
    display:flex;
    justify-content:space-between;
    align-items:center;
    font-weight:bold;
    border-bottom:1px solid #ccc;
    padding-bottom:4px;
    margin-bottom:6px;
}

.result-header button{
    width:22px;
    height:20px;
    padding:0;
    margin-left:3px;
    font-size:12px;
    cursor:pointer;
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

.live-nav-box{
    position:absolute;
    top:10px;
    left:50%;
    transform:translateX(-50%);
    z-index:9999;
    background:white;
    padding:8px 14px;
    border-radius:10px;
    box-shadow:0 2px 8px rgba(0,0,0,0.3);
    font-family:Arial;
    font-size:13px;
    font-weight:bold;
    display:none;
    max-width:80%;
    text-align:center;
}


/* TELEFON */
@media screen and (max-device-width: 900px){

    .route-control button{
        width:80px !important;
        height:28px !important;
        font-size:10px !important;
        font-weight:normal !important;
    }

    .route-control{
        padding:3px !important;
    }

    .leaflet-control-zoom{
        transform:scale(1.1) !important;
        transform-origin:top left !important;
    }

    .result-control{
        width:250px !important;
        font-size:12px !important;
        -webkit-overflow-scrolling: touch;
    }

    #map{
        height:85vh !important;
    }
}

</style>
</head>

<body>

<h3>Akıllı Engelli Navigasyon Sistemi</h3>
<div id="liveNavBox" class="live-nav-box">Navigasyon bekleniyor...</div>
<div id="map"></div>

<script src="https://unpkg.com/leaflet/dist/leaflet.js"></script>

<script>

let userLocation = null;
let targetMarker = null;
let userMarker = null;
let liveMarker = null;
let shpBounds = null;

let routeLayers = [null, null];
let selectedRouteIndex = 0;
let currentDirectionsList = [];
let routeData = [];
let navigationRoutes = [];

let watchId = null;
let spokenSteps = {};
let offRouteSpoken = false;

let currentTarget = null;
let rerouteInProgress = false;
let autoCenter = true;
let navigationActive = false;

// =========================
// SES
// =========================
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

function updateLiveNavText(text){
    let box = document.getElementById("liveNavBox");

    if(!box){
        return;
    }

    box.innerHTML = "🧭 " + text;
    box.style.display = "block";
}

function hideLiveNavText(){
    let box = document.getElementById("liveNavBox");

    if(box){
        box.style.display = "none";
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

// =========================
// HARİTA
// =========================
var map = L.map('map').setView([39.709,37.034],15);

L.tileLayer('https://{s}.tile.openstreetmap.org/{z}/{x}/{y}.png').addTo(map);

var RouteControl = L.Control.extend({
    options:{position:'topright'},

    onAdd:function(map){
        var div = L.DomUtil.create('div','route-control');

        div.innerHTML = `
            <button onclick="getMyLocation()">Konumum</button>
            <button onclick="zoomToShp()">Zoom</button>
            <button onclick="toggleAutoCenter()">Ortala</button>
            <button onclick="selectRoute(0)">1. Rota</button>
            <button onclick="selectRoute(1)">2. Rota</button>
            <button onclick="startLiveNavigation()">Başlat</button>
            <button onclick="stopLiveNavigation()">Durdur</button>
            <button onclick="clearAllForNewRoute()">Yeni Rota</button>
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
    <div class="result-header">
        <span>SONUÇLAR</span>
        <span>
            <button onclick="minimizeResultPanel()">—</button>
            <button onclick="maximizeResultPanel()">□</button>
            <button onclick="closeResultPanel()">×</button>
        </span>
    </div>
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
makeResultPanelDraggable();

resultContent.addEventListener("wheel", function(e){
    e.preventDefault();
    e.stopPropagation();
    resultContent.scrollTop += e.deltaY;
}, {passive:false});

let resultTouchStartY = 0;

resultContent.addEventListener("touchstart", function(e){
    resultTouchStartY = e.touches[0].clientY;
}, {passive:true});

resultContent.addEventListener("touchmove", function(e){
    e.preventDefault();
    e.stopPropagation();

    let y = e.touches[0].clientY;
    let diff = resultTouchStartY - y;

    resultContent.scrollTop += diff;
    resultTouchStartY = y;
}, {passive:false});
// =========================
// KATMANLAR
// =========================
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

function setStatus(text){
    let el = document.getElementById("navStatus");
    if(el){
        el.innerHTML = text;
    }
}

let panelDragging = false;
let panelOffsetX = 0;
let panelOffsetY = 0;

function makeResultPanelDraggable(){
    let header = document.querySelector(".result-header");

    header.addEventListener("mousedown", function(e){
        panelDragging = true;
        panelOffsetX = e.clientX - resultPanel.getBoundingClientRect().left;
        panelOffsetY = e.clientY - resultPanel.getBoundingClientRect().top;
        resultPanel.style.zIndex = 9999;
    });

    document.addEventListener("mousemove", function(e){
        if(!panelDragging) return;

        resultPanel.style.left = (e.clientX - panelOffsetX) + "px";
        resultPanel.style.top = (e.clientY - panelOffsetY) + "px";
        resultPanel.style.right = "auto";
    });

    document.addEventListener("mouseup", function(){
        panelDragging = false;
    });
}


function minimizeResultPanel(){
    resultPanel.style.height = "32px";
    resultContent.style.display = "none";
}

function maximizeResultPanel(){
    resultPanel.style.height = "auto";
    resultContent.style.display = "block";
    resultPanel.style.display = "block";
}

function closeResultPanel(){
    resultPanel.style.display = "none";
}
function toggleAutoCenter(){

    autoCenter = !autoCenter;

    if(autoCenter){

        if(userLocation){
            map.panTo([userLocation[1], userLocation[0]]);
        }

        speak("Ortala açık.");

    }else{

        speak("Ortala kapalı.");

    }
}

function clearAllForNewRoute(){
    stopLiveNavigation();

    if(targetMarker){
        map.removeLayer(targetMarker);
        targetMarker = null;
    }

    clearRoutes();

    routeData = [];
    navigationRoutes = [];
    currentDirectionsList = [];
    currentTarget = null;

    resultContent.innerHTML = "<b>Yeni rota için hedef seçin.</b><br><div id='navStatus'>Canlı takip kapalı</div>";
    hideLiveNavText();
    resultPanel.style.display = "block";
}

// =========================
// KONUM
// =========================
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

// =========================
// YARDIMCI MESAFE
// =========================
function distanceMeter(a, b){
    let R = 6371000;

    let lat1 = a[0] * Math.PI / 180;
    let lat2 = b[0] * Math.PI / 180;

    let dlat = (b[0] - a[0]) * Math.PI / 180;
    let dlng = (b[1] - a[1]) * Math.PI / 180;

    let x = Math.sin(dlat/2) * Math.sin(dlat/2) +
            Math.cos(lat1) * Math.cos(lat2) *
            Math.sin(dlng/2) * Math.sin(dlng/2);

    return 2 * R * Math.asin(Math.sqrt(x));
}

function minDistanceToCoords(lat, lng, coords){
    if(!coords || coords.length == 0){
        return 999999;
    }

    let minD = 999999;

    coords.forEach(function(p){
        let d = distanceMeter([lat,lng], [p[0],p[1]]);
        if(d < minD){
            minD = d;
        }
    });

    return minD;
}

// =========================
// OSRM METİN
// =========================
function bearingJS(a, b){
    let lat1 = a[0] * Math.PI / 180;
    let lat2 = b[0] * Math.PI / 180;
    let dLng = (b[1] - a[1]) * Math.PI / 180;

    let y = Math.sin(dLng) * Math.cos(lat2);
    let x = Math.cos(lat1) * Math.sin(lat2) -
            Math.sin(lat1) * Math.cos(lat2) * Math.cos(dLng);

    let brng = Math.atan2(y, x) * 180 / Math.PI;
    return (brng + 360) % 360;
}

function compassJS(angle){
    let dirs = [
        "Kuzey",
        "Kuzeydoğu",
        "Doğu",
        "Güneydoğu",
        "Güney",
        "Güneybatı",
        "Batı",
        "Kuzeybatı"
    ];

    return dirs[Math.round(angle / 45) % 8];
}



function osrmText(step){
    let type = step.maneuver.type;
    let modifier = step.maneuver.modifier;
    let exitNo = step.maneuver.exit;

    if(type == "arrive"){
        return "Geçiş noktasına ulaştınız. Erişilebilir yaya ağına geçin.";
    }

    if(type == "depart"){
        return "Araç rotası başladı. Yol üzerinde ilerleyin.";
    }

    if(type == "roundabout" || type == "rotary"){
        if(exitNo){
            return "döner kavşakta " + exitNo + ". çıkıştan çıkın";
        }
        return "döner kavşağa girin";
    }

    if(modifier == "right"){
        return "sağa dönün";
    }

    if(modifier == "left"){
        return "sola dönün";
    }

    if(modifier == "slight right"){
        return "hafif sağa yönelin";
    }

    if(modifier == "slight left"){
        return "hafif sola yönelin";
    }

    if(modifier == "sharp right"){
        return "keskin sağa dönün";
    }

    if(modifier == "sharp left"){
        return "keskin sola dönün";
    }

    if(modifier == "straight"){
        return "düz devam edin";
    }

    return "yol üzerinde ilerleyin";
}

function carInstructionText(baseText, distance){
    if(baseText.includes("Geçiş noktasına") || baseText.includes("Araç rotası başladı")){
        return baseText;
    }

    if(distance <= 20){
        return "Şimdi " + baseText + ".";
    }

    return Math.round(distance) + " metre sonra " + baseText + ".";
}

// =========================
// ROTA SEÇİMİ
// =========================
function clearRoutes(){
    for(let i=0;i<2;i++){
        if(routeLayers[i]){
            map.removeLayer(routeLayers[i]);
            routeLayers[i] = null;
        }
    }

    currentDirectionsList = [];
    navigationRoutes = [];
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
        updateResultDirections();
    }

    speak((index + 1) + ". rota seçildi.");
}

function updateResultDirections(){

    if(!routeData[selectedRouteIndex]){
        return;
    }

    let route = routeData[selectedRouteIndex];

    let html = "";

    html += "<b>Seçili rota: " + (selectedRouteIndex + 1) + ". rota</b><br>";

    if(route.mode == "car_plus_walk"){
        html += "Geçiş: " + route.entry_name + "<br>";
        html += "Araç: " + Math.round(route.access_distance) + " m<br>";
    }else{
        html += "Doğrudan erişilebilir ağ<br>";
    }

    html += "Yaya: " + Math.round(route.walk_distance) + " m<br>";
    html += "Toplam: " + Math.round(route.total_distance) + " m<br>";

    html += "<hr>";
    html += "<div id='navStatus' style='font-weight:bold;margin-bottom:6px;color:#333;'>Canlı takip kapalı</div>";
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

// =========================
// OSRM ÇİZİM + ARAÇ ADIMLARI
// =========================
function drawOSRM(userLng, userLat, entryX, entryY, group, routeIndex, callback){

    fetch(`https://router.project-osrm.org/route/v1/driving/${userLng},${userLat};${entryX},${entryY}?overview=full&geometries=geojson&steps=true`)
    .then(r=>r.json())
    .then(osrm=>{

        let carSteps = [];
        let carLineCoords = [];

        if(osrm.routes && osrm.routes.length > 0){

            let coords = osrm.routes[0].geometry.coordinates;
            let roadLine = coords.map(c => [c[1], c[0]]);

            carLineCoords = roadLine;
            if(roadLine.length > 1){
    let firstAngle = bearingJS(roadLine[0], roadLine[1]);
    let firstDir = compassJS(firstAngle);

    carSteps.push({
        lat: roadLine[0][0],
        lng: roadLine[0][1],
        text: firstDir + " yönünde ilerleyin.",
        threshold: 999,
        mode: "car"
    });
}

            L.polyline(roadLine,{
                color:"orange",
                weight:3
            }).addTo(group);

            let steps = osrm.routes[0].legs[0].steps;

            steps.forEach(function(s){
                let baseText = osrmText(s);

                if(s.maneuver.type == "depart"){
                    carSteps.push({
                        lat: s.maneuver.location[1],
                        lng: s.maneuver.location[0],
                        text: baseText,
                        threshold: 999,
                        mode: "car"
                    });
                }else if(s.maneuver.type == "arrive"){
                    carSteps.push({
                        lat: s.maneuver.location[1],
                        lng: s.maneuver.location[0],
                        text: "Geçiş noktasına ulaştınız. Erişilebilir yaya ağına geçin.",
                        threshold: 25,
                        mode: "transition"
                    });
                }else{
                    [500, 200, 100, 50, 20].forEach(function(th){
                        carSteps.push({
                            lat: s.maneuver.location[1],
                            lng: s.maneuver.location[0],
                            text: carInstructionText(baseText, th),
                            threshold: th,
                            mode: "car"
                        });
                    });
                }
            });

            carSteps.push({
                lat: entryY,
                lng: entryX,
                text: "Erişilebilir yaya ağına geçin.",
                threshold: 20,
                mode: "transition"
            });

        }else{

            L.polyline([
                [userLat,userLng],
                [entryY,entryX]
            ],{
                color:"orange",
                weight:3
            }).addTo(group);

            carLineCoords = [
                [userLat,userLng],
                [entryY,entryX]
            ];

            carSteps.push({
                lat: entryY,
                lng: entryX,
                text: "Erişilebilir yaya ağına geçin.",
                threshold: 20,
                mode: "transition"
            });
        }

        navigationRoutes[routeIndex].carSteps = carSteps;
        navigationRoutes[routeIndex].carLine = carLineCoords;

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

        navigationRoutes[routeIndex].carSteps = [{
            lat: entryY,
            lng: entryX,
            text: "Erişilebilir yaya ağına geçin.",
            threshold: 20,
            mode: "transition"
        }];

        navigationRoutes[routeIndex].carLine = [
            [userLat,userLng],
            [entryY,entryX]
        ];

        callback();
    });
}

// =========================
// ROTALARI ÇİZ
// =========================
function drawRoutes(data){

    clearRoutes();

    if(!data.routes || data.routes.length == 0){
        alert("Rota bulunamadı.");
        return;
    }

    routeData = data.routes;
    selectedRouteIndex = 0;

    let html = "";

    data.routes.forEach(function(route, index){

        let group = L.layerGroup();
        let color = index == 0 ? "blue" : "green";

        let walkLine = route.walk_path.map(p=>[p[1],p[0]]);

        navigationRoutes[index] = {
            carSteps: [],
            carLine: [],
            walkSteps: [],
            walkLine: walkLine,
            directions: route.directions
        };

        if(route.mode == "car_plus_walk" && route.entry){

            drawOSRM(
                userLocation[0],
                userLocation[1],
                route.entry.x,
                route.entry.y,
                group,
                index,
                function(){}
            );

            L.circleMarker([route.entry.y, route.entry.x],{
                radius:5,
                color:"black",
                fillColor:"orange",
                fillOpacity:1
            }).addTo(group);
        }

        if(route.walk_steps){
            navigationRoutes[index].walkSteps = route.walk_steps.map(function(s){
                return {
                    lat: s.y,
                    lng: s.x,
                    text: s.text,
                    threshold: s.threshold || 20,
                    mode: "walk"
                };
            });
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
    html += "<b>Varsayılan olarak 1. rota seçildi.</b><br>";
    html += "İstersen 1. Rota / 2. Rota butonlarıyla seçim yap.<br><br>";
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

// =========================
// CANLI TAKİP
// =========================
function startLiveNavigation(){

    if(!routeData[selectedRouteIndex]){
        alert("Önce rota oluşturun ve rota seçin.");
        return;
    }

    if(watchId){
        navigator.geolocation.clearWatch(watchId);
        watchId = null;
    }

    spokenSteps = {};
    offRouteSpoken = false;
    rerouteInProgress = false;
    navigationActive = true;

    setStatus("Canlı takip aktif");

    if(currentDirectionsList && currentDirectionsList.length > 0){
        speak(currentDirectionsList[0]);
        updateLiveNavText(currentDirectionsList[0]);
        spokenSteps["start"] = true;
    }else{
        speak("Canlı navigasyon başlatıldı.");
        updateLiveNavText("Canlı navigasyon başlatıldı.");
    }

    watchId = navigator.geolocation.watchPosition(function(pos){

        let lat = pos.coords.latitude;
        let lng = pos.coords.longitude;

        userLocation = [lng, lat];

        if(liveMarker){
            map.removeLayer(liveMarker);
        }

        liveMarker = L.circleMarker([lat,lng],{
            radius:6,
            color:"blue",
            fillColor:"blue",
            fillOpacity:1
        }).addTo(map);

        if(autoCenter){
            map.panTo([lat,lng]);
        }

        let nav = navigationRoutes[selectedRouteIndex];

        if(!nav){
            return;
        }

        let allSteps = [];

        if(nav.carSteps){
            nav.carSteps.forEach(function(s, i){
                let c = Object.assign({}, s);
                c._key = "car_" + i + "_" + s.threshold;
                allSteps.push(c);
            });
        }

        if(nav.walkSteps){
            nav.walkSteps.forEach(function(s, i){
                let w = Object.assign({}, s);
                w._key = "walk_" + i + "_" + s.threshold;
                allSteps.push(w);
            });
        }

        let bestStep = null;
        let bestKey = null;
        let bestDist = 999999;

        allSteps.forEach(function(step){

            let d = distanceMeter([lat,lng], [step.lat,step.lng]);

            if(d < bestDist && !spokenSteps[step._key]){
                bestDist = d;
                bestStep = step;
                bestKey = step._key;
            }
        });

        if(bestStep && bestDist <= bestStep.threshold && !spokenSteps[bestKey]){
            speak(bestStep.text);
            updateLiveNavText(bestStep.text);
            spokenSteps[bestKey] = true;
        }

        // Sapma kontrolü
        let carDist = minDistanceToCoords(lat, lng, nav.carLine);
        let walkDist = minDistanceToCoords(lat, lng, nav.walkLine);

        let minRouteDist = Math.min(carDist, walkDist);

        let tolerance = 15;

        if(carDist < walkDist){
            tolerance = 50;   // araç toleransı
        }else{
            tolerance = 15;   // yaya toleransı
        }

        if(minRouteDist > tolerance && !rerouteInProgress && currentTarget){
            rerouteFromCurrentLocation();
        }

    }, function(){
        alert("Canlı konum takip edilemedi.");
    }, {
        enableHighAccuracy:true,
        maximumAge:1000,
        timeout:10000
    });
}

function rerouteFromCurrentLocation(){

    if(!userLocation || !currentTarget){
        return;
    }

    rerouteInProgress = true;
    offRouteSpoken = true;

    speak("Rotadan çıktınız. Yeni rota hesaplanıyor.");
    updateLiveNavText("Rotadan çıktınız. Yeni rota hesaplanıyor.");
    setStatus("Yeni rota hesaplanıyor...");

    fetch(`/smart_route?ux=${userLocation[0]}&uy=${userLocation[1]}&tx=${currentTarget[0]}&ty=${currentTarget[1]}`)
    .then(r=>r.json())
    .then(d=>{

        if(d.status != "ok"){
            speak("Yeni rota bulunamadı.");
            setStatus("Yeni rota bulunamadı");
            rerouteInProgress = false;
            return;
        }

        drawRoutes(d);
        selectedRouteIndex = 0;
        selectRoute(0);

        spokenSteps = {};
        offRouteSpoken = false;
        rerouteInProgress = false;

        setStatus("Yeni rota oluşturuldu. Canlı takip aktif.");
        speak("Yeni rota oluşturuldu.");
        updateLiveNavText("Yeni rota oluşturuldu.");

    })
    .catch(()=>{
        speak("Yeni rota hesaplanamadı.");
        setStatus("Yeni rota hesaplanamadı");
        rerouteInProgress = false;
    });
}

function stopLiveNavigation(){

    if(watchId){
        navigator.geolocation.clearWatch(watchId);
        watchId = null;
    }

    spokenSteps = {};
    offRouteSpoken = false;
    rerouteInProgress = false;
    navigationActive = false;

    if(liveMarker){
        map.removeLayer(liveMarker);
        liveMarker = null;
    }

    setStatus("Canlı takip kapalı");
    hideLiveNavText();
    speak("Canlı takip durduruldu.");
}

// =========================
// HEDEF SEÇ
// =========================
map.on('click', function(e){

    if(!userLocation){
        alert("Önce Konumum butonuna basın.");
        return;
    }

    let target = [e.latlng.lng, e.latlng.lat];
    currentTarget = target;

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

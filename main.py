from mavsdk import System
from os import listdir, path
import json, asyncio, multiprocessing, requests
from flask import Flask, render_template, request, send_from_directory
from flask_cors import CORS

WebGUI = Flask(__name__)

# =============asynchronous functions=============
async def establish_connect(link):
    drone = System()
    await drone.connect(system_address=link)
    return drone


async def drone_is_armed(drone):
    async for is_armed in drone.telemetry.armed():
        return is_armed


async def drone_position(drone):
    async for position in drone.telemetry.position():
        return position


async def drone_is_in_air(drone):
    async for flight_mode in drone.telemetry.flight_mode():
        return flight_mode


async def drone_batt_stat(drone):
    async for battery in drone.telemetry.battery():
        return battery


async def make_drone_arm(curr_drone_data, drone) -> None:
    if not curr_drone_data['armed']:
        await drone.action.arm()
        
async def make_drone_disarm(curr_drone_data, drone) -> None:
    if curr_drone_data['armed']:
        await drone.action.disarm()

async def make_drone_takeoff(curr_drone_data, drone) -> None:
    if not curr_drone_data['armed']:
        await make_drone_arm(curr_drone_data, drone)
    await drone.action.takeoff()

async def make_drone_rtl(curr_drone_data, drone) -> None:
    if curr_drone_data['armed']:
        await drone.action.return_to_launch()

async def make_drone_goToCords(curr_drone_data, drone, position) -> None:
    if curr_drone_data['armed']:
        async for terrain_info in drone.telemetry.home():
            absolute_altitude = terrain_info.absolute_altitude_m
            break
        flying_alt = absolute_altitude + float(position['alt'])
        await drone.action.goto_location(float(position['lat']),float(position['lon']),flying_alt, float(0))

async def make_drone_land(curr_drone_data, drone) -> None:
    if curr_drone_data['armed']:
        await drone.action.land()

async def updater() -> None:
    await asyncio.sleep(3)
    drone_connects = {}
    drone_data = {}
    drone_tasks = {}
    response = requests.get("http://127.0.0.1:5000/update?c=getdict&arg={}")
    drone_data = response.json()
    for drone_id in dict(drone_data):
        drone_connects[drone_id] = await establish_connect(drone_data[drone_id]["link"])
        async for state in drone_connects[drone_id].core.connection_state():
            if state.is_connected:
                print(f"{drone_id} Connected to drone!")
                break
    while True:
        for drone_id in dict(drone_data):
            temp_dict = {}
            temp_dict['ID'] = drone_id
            drone_data[drone_id]['position'] = await drone_position(drone_connects[drone_id])
            temp_dict['data'] = dict(b.split(': ') for b in str(drone_data[drone_id]['position']).split('[')[1][:-1].split(', '))
            requests.get(f"http://127.0.0.1:5000/update?c=updatepos&arg={json.dumps(temp_dict)}")
            drone_data[drone_id]['armed'] = await drone_is_armed(drone_connects[drone_id])
            temp_dict['data']=drone_data[drone_id]['armed']
            requests.get(f"http://127.0.0.1:5000/update?c=updatearmed&arg={json.dumps(temp_dict)}")
            drone_data[drone_id]['battery'] = await drone_batt_stat(drone_connects[drone_id])
            temp_dict['data'] = dict(b.split(': ') for b in str(drone_data[drone_id]['battery']).split('[')[1][:-1].split(', '))
            print(temp_dict['data'])
            requests.get(f"http://127.0.0.1:5000/update?c=updatebattery&arg={json.dumps(temp_dict)}")
            response = requests.get("http://127.0.0.1:5000/update?c=getdict&arg={}")
            drone_data = response.json()
            await update_drone_task(drone_data[drone_id],drone_connects[drone_id])
            temp_dict['data']=drone_data[drone_id]['cmd_queue']
            requests.get(f"http://127.0.0.1:5000/update?c=updatecmd&arg={json.dumps(temp_dict)}")
                

async def update_drone_task(curr_data,drone) -> None:
    if len(curr_data['cmd_queue'])>0:
        mapping = {
            'arming_task': make_drone_arm,
            'disarming_task': make_drone_disarm,
            'takeoff_task': make_drone_takeoff,
            'land_task': make_drone_land,
            'rtl_task': make_drone_rtl,
            'goto_task': make_drone_goToCords 
        }
        next_task=curr_data['cmd_queue'].pop(0).split(' ')
        print(f"------\n\n\n\---{curr_data['cmd_queue']}")
        if len(next_task) == 1: await mapping[next_task[0]](curr_data,drone)
        else:
             a=['lon','lat','alt']
             print(next_task);
             position = {a[i]:next_task[1].split(";")[i] for i in range(3)}
             await mapping[next_task[0]](curr_data,drone,position)

# ==================functions====================
def drone_driver(drone_data) -> None:
    asyncio.run(updater())

def initialize_drone(drone_data) -> None:
    for drone_json in [f for f in listdir("./drones/") if path.isfile(path.join("./drones/", f))]:
        dj = open("./drones/" + drone_json)
        dd = json.load(dj)
        dd['cmd_queue']=[]
        drone_data[dd['id']] = dd
        print(drone_data[dd['id']])
        print(f"New UAV {dd['common_name']} added with ID : {dd['id']} with target on {dd['link']}")

def main() -> None:
    initialize_drone(drone_data)
    multiprocessing.Process(target=drone_driver, args=(drone_data,)).start()
    cors = CORS(WebGUI, resources={r"/": {"origins": "*"}})
    WebGUI.run()
    
def CMD_GET_web_driver(command, arg = None) -> str:
    global drone_data
    if command == "dronelist":
        ret = []
        for i in dict(drone_data): 
        	ret.append(i)
        return json.dumps(ret)
    if command == "dronestat":
        if arg['ID'] in dict(drone_data):
            ret = {}
            ret['name'] = drone_data[arg['ID']]['common_name']
            ret['pos'] = drone_data[arg['ID']]['position']
            ret['armed'] = drone_data[arg['ID']]['armed']
            ret['battery'] = drone_data[arg['ID']]['battery']
            return json.dumps(ret)
    if command == "updatepos":
        drone_data[arg['ID']]['position'] = arg['data']
        return 'ok'
    if command == "updatearmed":
        drone_data[arg['ID']]['armed'] = arg['data']
        return 'ok'
    if command == "updatebattery":
        print(arg)
        drone_data[arg['ID']]['battery'] = arg['data']
        return 'ok'
    if command == "updatecmd":
        drone_data[arg['ID']]['cmd_queue'] = arg['data']
        return 'ok'
    if command == "getdict":
       return json.dumps(drone_data)
    if command == "dronearm":
        if arg['ID'] in dict(drone_data):
            drone_data[arg['ID']]['cmd_queue'].append("arming_task")
        return json.dumps('ok')
    if command == "dronertl":
        if arg['ID'] in dict(drone_data):
            drone_data[arg['ID']]['cmd_queue'].append("rtl_task")
        return json.dumps('ok')
    if command == "dronedisarm":
        if arg['ID'] in dict(drone_data):
            drone_data[arg['ID']]['cmd_queue'].append("disarming_task")
            return json.dumps('ok')
    if command == "dronetakeoff":
        if arg['ID'] in dict(drone_data):
            drone_data[arg['ID']]['cmd_queue'].append("takeoff_task")
            return json.dumps('ok')
    if command == "droneland":
        if arg['ID'] in dict(drone_data):
            drone_data[arg['ID']]['cmd_queue'].append("land_task")
            return json.dumps('ok')
    if command == "dronegoto":
        if arg['ID'] in dict(drone_data):
            drone_data[arg['ID']]['cmd_queue'].append(f'goto_task {arg["lon"]};{arg["lat"]};{arg["alt"]}')
            return json.dumps('ok')
    return 'null'

# ==================Based on Flask===============
@WebGUI.route('/', methods=['GET'])
def WebGUI_index():
    return render_template('index.html')

@WebGUI.route('/update', methods=['GET'])
def WebGUI_updater():
    if request.method == 'GET':
        awaiting = request.args.get('c')
        arg = request.args.get('arg')
        if arg != None: 
        	return CMD_GET_web_driver(awaiting, json.loads(arg))
    return 'null'

@WebGUI.route('/openlayers/<path:path>')
def WebGUI_static(path):
    return send_from_directory('openlayers', path)
# ====================Defaults===================

if __name__ == "__main__":
    drone_data = {}
    main()

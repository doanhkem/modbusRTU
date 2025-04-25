


import json
import time
from datetime import datetime
from pymodbus.client.sync import ModbusSerialClient
from pymodbus.payload import BinaryPayloadDecoder
from pymodbus.constants import Endian
import paho.mqtt.client as mqtt
import threading
from queue import Queue

# Load device configuration
with open("deviceConfig.conf", "r") as f:
    device_config = json.load(f)

# Load MQTT configuration
with open("appConfig.conf", "r") as f:
    app_config = json.load(f)

mqtt_conf = app_config["mqtt"]

# MQTT setup
client_mqtt = mqtt.Client(client_id=mqtt_conf["clientID"])
client_mqtt.username_pw_set(mqtt_conf["user"], mqtt_conf["password"])

# Queue to store MQTT messages when offline
mqtt_queue = Queue()
mqtt_connected = False

# Cấu hình thời gian gửi MQTT
MQTT_INTERVAL_MINUTES = 0.5

# Bộ đệm lưu dữ liệu mới nhất
latest_data = {}

def value_decode(registers, typeString, size, byteorder, wordorder, fractionDigit=0, pf=0):

    decoder = BinaryPayloadDecoder.fromRegisters(
        registers, byteorder=Endian.Big, wordorder=Endian.Big
    )
    # print(byteorder_val,wordorder_val)
    if typeString == "int16":
        value = decoder.decode_16bit_int()
    elif typeString == "uint16":
        value = decoder.decode_16bit_uint()
    elif typeString == "int32":
        value = decoder.decode_32bit_int()
    elif typeString == "uint32":
        value = decoder.decode_32bit_uint()
    elif typeString == "float16":
        value = decoder.decode_16bit_float()
    elif typeString == "float32":
        value = decoder.decode_32bit_float()
    elif typeString == "string":
        value = decoder.decode_string(size).decode(errors="ignore")
        return value
    else:
        return "Invalid type"
    if isinstance(value, (float, int)):
        value = value * (10 ** pf)
        value = round(value, fractionDigit)

    return value

def on_connect(client, userdata, flags, rc):
    global mqtt_connected
    if rc == 0:
        mqtt_connected = True
        print("[MQTT] Connected successfully")
        # Gửi lại tất cả các gói tin trong hàng đợi
        while not mqtt_queue.empty():
            topic, payload = mqtt_queue.get()
            client.publish(topic, payload, qos=mqtt_conf["QoS"])
            print(f"[MQTT] Republished from queue to {topic}:", payload)
    else:
        print("[MQTT] Connection failed with code", rc)

def on_disconnect(client, userdata, rc):
    global mqtt_connected
    mqtt_connected = False
    print("[MQTT] Disconnected")

client_mqtt.on_connect = on_connect
client_mqtt.on_disconnect = on_disconnect
client_mqtt.connect(mqtt_conf["ip"], mqtt_conf["port"], keepalive=mqtt_conf["keepAliveTime"])
client_mqtt.loop_start()

def read_devices():
    while True:
        for thing_id, device in device_config["modbusrtu"].items():
            client = ModbusSerialClient(
                method='rtu',
                port=device["port"],
                baudrate=int(device["baudrate"]),
                timeout=float(device["minResponseTimeInMiliSecond"]) / 1000
            )

            if not client.connect():
                print(f"[ERROR] Cannot connect to {thing_id}")
                continue

            print(f"[INFO] Connected to {thing_id}")

            wordorder = device["dataFormat"].get("wordOrder")
            byteorder = device["dataFormat"].get("byteOrder")

            collected = []

            for task in device["tasks"].get("read_registers", []):
                offset = task["offSet"]
                size = task["size"]
                data_type = task["dataType"]
                fraction_digit = task.get("fractionDigit", 0)
                pf_multiplier = task.get("PF", 0)


                try:
                    response = client.read_holding_registers(offset, size, unit=device["unitID"])
                    if not response or not hasattr(response, 'registers'):
                        print(f"[WARN] No response for {thing_id} {task['tagName']}")
                        continue
                    value = value_decode(response.registers, data_type, size, byteorder, wordorder, fractionDigit=fraction_digit,pf=pf_multiplier)
                    collected.append({task["tagName"]: value})
                except Exception as e:
                    print(f"[ERROR] Reading {task['tagName']} failed: {e}")
                time.sleep(0.5)

            latest_data[thing_id] = {
                "type": device["deviceType"],
                "data": collected,
                "timeStamp": str(datetime.now())
            }

            client.close()

        time.sleep(10)  # Đọc mỗi 1 phút

def send_mqtt_loop():
    while True:
        time.sleep(MQTT_INTERVAL_MINUTES * 60)

        for thing_id, payload in latest_data.items():
            topic = f"{thing_id}/reportData"
            payload_str = json.dumps(payload)
            if mqtt_connected:
                result = client_mqtt.publish(topic, payload_str, qos=mqtt_conf["QoS"])
                if result.rc != mqtt.MQTT_ERR_SUCCESS:
                    print(f"[WARN] Publish failed, queued {topic}")
                    mqtt_queue.put((topic, payload_str))
                else:
                    print(f"[MQTT] Published to {topic}:", payload_str)
            else:
                print(f"[MQTT] MQTT not connected, queued {topic}")
                mqtt_queue.put((topic, payload_str))

read_thread = threading.Thread(target=read_devices)
send_thread = threading.Thread(target=send_mqtt_loop)

read_thread.start()
send_thread.start()

read_thread.join()
send_thread.join()

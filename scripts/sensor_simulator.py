"""
水车传感器模拟器
模拟汉代龙骨水车的传感器数据上报，包含：
- 转速 (rotational_speed, rpm)
- 扭矩 (torque, N·m)
- 提水量 (water_lift, L/min)
- 水位差 (water_level_diff, m)
- 链张力 (chain_tension, N)
- 刮水阻力 (scrape_resistance, N)
"""
import sys
import os
import time
import json
import random
import math
import requests
import asyncio
import websockets
from datetime import datetime, timezone
from dataclasses import dataclass, field
from typing import Optional, List

sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', 'backend'))

BACKEND_URL = os.getenv("BACKEND_URL", "http://localhost:8000")
WS_URL = os.getenv("WS_URL", "ws://localhost:8000")
REPORT_INTERVAL = 60


@dataclass
class WaterWheelConfig:
    wheel_id: str = "han_dynasty_wheel_001"
    location: str = "shaanxi_han_ruins"
    nominal_speed: float = 15.0
    nominal_torque: float = 80.0
    nominal_water_lift: float = 180.0
    nominal_level_diff: float = 2.0
    chain_length: float = 12.0
    num_blades: int = 24
    max_chain_tension: float = 5000.0
    efficiency_threshold: float = 0.3


@dataclass
class SensorData:
    wheel_id: str
    location: str
    timestamp: str
    rotational_speed: float
    torque: float
    water_lift: float
    water_level_diff: float
    chain_tension: float
    scrape_resistance: float
    drive_torque: float
    efficiency: float
    anomaly: Optional[str] = None


class WaterWheelSimulator:
    def __init__(self, config: WaterWheelConfig):
        self.config = config
        self.current_speed = config.nominal_speed
        self.chain_wear = 0.0
        self.runtime_hours = 0.0
        self.is_broken = False
        self.broken_blade_index = -1
        self.speed_modifier = 1.0
        self.torque_modifier = 1.0
        self.data_history: List[SensorData] = []
        
    def set_operating_condition(self, speed_factor: float = 1.0, torque_factor: float = 1.0):
        self.speed_modifier = max(0.2, min(speed_factor, 2.0))
        self.torque_modifier = max(0.5, min(torque_factor, 2.0))
    
    def induce_chain_break(self):
        self.is_broken = True
        self.broken_blade_index = random.randint(0, self.config.num_blades - 1)
        
    def repair_chain(self):
        self.is_broken = False
        self.broken_blade_index = -1
        self.chain_wear = max(0, self.chain_wear - 0.1)
    
    def _wear_progression(self):
        self.runtime_hours += REPORT_INTERVAL / 3600
        self.chain_wear = min(1.0, self.chain_wear + random.uniform(0.0001, 0.0005))
    
    def _generate_noise(self, base: float, noise_level: float = 0.05) -> float:
        return base * (1 + random.uniform(-noise_level, noise_level))
    
    def _calculate_efficiency(self, speed: float, torque: float, water_lift: float) -> float:
        power_input = torque * speed * 2 * math.pi / 60
        if power_input <= 0:
            return 0.0
        water_power = (water_lift / 60) * 9.81 * self.config.nominal_level_diff
        efficiency = water_power / power_input
        efficiency = efficiency * (1 - self.chain_wear * 0.3)
        return max(0.0, min(1.0, efficiency))
    
    def _calculate_chain_tension(self, torque: float, speed: float) -> float:
        base_tension = torque / 0.15
        centrifugal = self.config.chain_length * speed * speed * 0.5
        wear_factor = 1 + self.chain_wear * 0.2
        tension = (base_tension + centrifugal) * wear_factor * self.torque_modifier
        return max(0, min(tension, self.config.max_chain_tension * 1.2))
    
    def _calculate_scrape_resistance(self, speed: float, level_diff: float) -> float:
        base_resistance = speed * level_diff * 25
        water_viscosity_factor = 1 + 0.1 * math.sin(self.runtime_hours * 0.1)
        wear_factor = 1 + self.chain_wear * 0.4
        return base_resistance * water_viscosity_factor * wear_factor
    
    def generate_reading(self) -> SensorData:
        self._wear_progression()
        
        anomaly = None
        
        if self.is_broken:
            self.current_speed = max(0, self.current_speed * 0.95 - random.uniform(0, 0.5))
            torque = random.uniform(0, 5)
            water_lift = max(0, random.uniform(0, 5))
            anomaly = f"CHAIN_BROKEN: blade_{self.broken_blade_index}"
        else:
            target_speed = self.config.nominal_speed * self.speed_modifier
            self.current_speed += (target_speed - self.current_speed) * 0.1
            self.current_speed = self._generate_noise(self.current_speed, 0.03)
            
            torque = self.config.nominal_torque * self.torque_modifier
            torque = self._generate_noise(torque, 0.04)
            torque = torque * (1 + self.chain_wear * 0.25)
            
            efficiency_raw = 0.7 - 0.2 * abs(self.current_speed - self.config.nominal_speed) / self.config.nominal_speed
            water_lift = (torque * self.current_speed * efficiency_raw * 0.25)
            water_lift = max(0, water_lift)
            water_lift = self._generate_noise(water_lift, 0.06)
            
            if self.chain_wear > 0.8 and random.random() < 0.02:
                self.induce_chain_break()
                anomaly = f"CHAIN_BROKEN: blade_{self.broken_blade_index}"
        
        level_diff = self.config.nominal_level_diff
        level_diff += random.uniform(-0.05, 0.05)
        level_diff += 0.1 * math.sin(self.runtime_hours * 0.05)
        level_diff = max(0.5, level_diff)
        
        chain_tension = self._calculate_chain_tension(torque, self.current_speed)
        scrape_resistance = self._calculate_scrape_resistance(self.current_speed, level_diff)
        
        drive_torque = torque + scrape_resistance * 0.15
        efficiency = self._calculate_efficiency(self.current_speed, drive_torque, water_lift)
        
        if not anomaly and efficiency < self.config.efficiency_threshold and self.current_speed > 1:
            anomaly = f"LOW_EFFICIENCY: {efficiency:.3f} < {self.config.efficiency_threshold}"
        
        if not anomaly and chain_tension > self.config.max_chain_tension:
            anomaly = f"CHAIN_OVERLOAD: tension={chain_tension:.0f}N"
        
        data = SensorData(
            wheel_id=self.config.wheel_id,
            location=self.config.location,
            timestamp=datetime.now(timezone.utc).isoformat(),
            rotational_speed=round(self.current_speed, 3),
            torque=round(torque, 3),
            water_lift=round(water_lift, 3),
            water_level_diff=round(level_diff, 3),
            chain_tension=round(chain_tension, 2),
            scrape_resistance=round(scrape_resistance, 2),
            drive_torque=round(drive_torque, 3),
            efficiency=round(efficiency, 4),
            anomaly=anomaly
        )
        
        self.data_history.append(data)
        if len(self.data_history) > 1000:
            self.data_history = self.data_history[-1000:]
        
        return data
    
    def post_to_backend(self, data: SensorData) -> bool:
        try:
            url = f"{BACKEND_URL}/api/sensor/data"
            payload = {
                "wheel_id": data.wheel_id,
                "location": data.location,
                "timestamp": data.timestamp,
                "rotational_speed": data.rotational_speed,
                "torque": data.torque,
                "water_lift": data.water_lift,
                "water_level_diff": data.water_level_diff,
                "chain_tension": data.chain_tension,
                "scrape_resistance": data.scrape_resistance,
                "drive_torque": data.drive_torque,
                "efficiency": data.efficiency,
                "anomaly": data.anomaly
            }
            response = requests.post(url, json=payload, timeout=10)
            if response.status_code == 200:
                print(f"✓ 数据上报成功 - 转速:{data.rotational_speed:.1f}rpm 效率:{data.efficiency:.2%}")
                if data.anomaly:
                    print(f"  ⚠ 异常: {data.anomaly}")
                return True
            else:
                print(f"✗ 上报失败: HTTP {response.status_code}")
                return False
        except Exception as e:
            print(f"✗ 上报异常: {e}")
            return False
    
    async def send_via_websocket(self, data: SensorData):
        try:
            uri = f"{WS_URL}/ws/sensor/{data.wheel_id}"
            async with websockets.connect(uri) as ws:
                payload = json.dumps({
                    "timestamp": data.timestamp,
                    "rotational_speed": data.rotational_speed,
                    "torque": data.torque,
                    "water_lift": data.water_lift,
                    "water_level_diff": data.water_level_diff,
                    "chain_tension": data.chain_tension,
                    "scrape_resistance": data.scrape_resistance,
                    "drive_torque": data.drive_torque,
                    "efficiency": data.efficiency,
                    "anomaly": data.anomaly
                })
                await ws.send(payload)
                resp = await ws.recv()
                print(f"✓ WebSocket发送成功: {resp[:50]}...")
        except Exception as e:
            print(f"✗ WebSocket失败: {e}")


def interactive_menu():
    print("\n" + "="*60)
    print("  汉代龙骨水车传感器模拟器")
    print("="*60)
    
    config = WaterWheelConfig()
    sim = WaterWheelSimulator(config)
    
    while True:
        print("\n请选择操作:")
        print("  1) 开始自动模拟 (每分钟上报)")
        print("  2) 生成单次数据并上报")
        print("  3) 调整工况参数")
        print("  4) 模拟链板断裂")
        print("  5) 修复链板")
        print("  6) 查看最近10条数据")
        print("  7) 查看当前状态")
        print("  0) 退出")
        
        choice = input("\n请输入选项: ").strip()
        
        if choice == "0":
            print("退出模拟器")
            break
        
        elif choice == "1":
            duration = input("模拟时长(分钟，回车=无限): ").strip()
            total = int(duration) if duration.isdigit() else -1
            count = 0
            try:
                while total < 0 or count < total:
                    data = sim.generate_reading()
                    sim.post_to_backend(data)
                    count += 1
                    if total < 0 or count < total:
                        for i in range(REPORT_INTERVAL, 0, -1):
                            print(f"\r  下次上报倒计时: {i}秒 ", end="", flush=True)
                            time.sleep(1)
                        print()
            except KeyboardInterrupt:
                print("\n模拟已停止")
        
        elif choice == "2":
            data = sim.generate_reading()
            sim.post_to_backend(data)
            print(f"  时间: {data.timestamp}")
            print(f"  转速: {data.rotational_speed:.2f} rpm")
            print(f"  扭矩: {data.torque:.2f} N·m")
            print(f"  提水量: {data.water_lift:.2f} L/min")
            print(f"  水位差: {data.water_level_diff:.3f} m")
            print(f"  链张力: {data.chain_tension:.1f} N")
            print(f"  刮水阻力: {data.scrape_resistance:.1f} N")
            print(f"  驱动力矩: {data.drive_torque:.2f} N·m")
            print(f"  效率: {data.efficiency:.2%}")
            if data.anomaly:
                print(f"  异常: {data.anomaly}")
        
        elif choice == "3":
            sf = input(f"转速倍率 (当前={sim.speed_modifier:.2f}): ").strip()
            tf = input(f"扭矩倍率 (当前={sim.torque_modifier:.2f}): ").strip()
            try:
                sf_val = float(sf) if sf else sim.speed_modifier
                tf_val = float(tf) if tf else sim.torque_modifier
                sim.set_operating_condition(sf_val, tf_val)
                print(f"工况已更新: 转速倍率={sf_val}, 扭矩倍率={tf_val}")
            except ValueError:
                print("输入无效")
        
        elif choice == "4":
            sim.induce_chain_break()
            print(f"⚠ 已模拟链板断裂，断裂位置: blade_{sim.broken_blade_index}")
        
        elif choice == "5":
            sim.repair_chain()
            print("✓ 链板已修复")
        
        elif choice == "6":
            print(f"\n最近{min(10, len(sim.data_history))}条数据:")
            for d in sim.data_history[-10:]:
                status = "⚠ " if d.anomaly else "  "
                print(f"  {status}[{d.timestamp[11:19]}] 速度={d.rotational_speed:5.1f} 效率={d.efficiency:6.2%} 提水={d.water_lift:6.1f}L")
        
        elif choice == "7":
            print(f"\n当前模拟器状态:")
            print(f"  水车ID: {config.wheel_id}")
            print(f"  地点: {config.location}")
            print(f"  运行时长: {sim.runtime_hours:.2f} 小时")
            print(f"  链条磨损: {sim.chain_wear:.2%}")
            print(f"  链板状态: {'断裂⚠' if sim.is_broken else '正常✓'}")
            print(f"  转速倍率: {sim.speed_modifier:.2f}x")
            print(f"  扭矩倍率: {sim.torque_modifier:.2f}x")
            print(f"  已生成数据: {len(sim.data_history)} 条")


def parse_args():
    import argparse
    parser = argparse.ArgumentParser(description="汉代龙骨水车传感器模拟器")
    parser.add_argument("--auto", action="store_true", help="自动模拟模式")
    parser.add_argument("--speed", type=float, default=15.0, help="额定转速 rpm (默认: 15)")
    parser.add_argument("--level", type=float, default=2.0, help="额定水位差 m (默认: 2.0)")
    parser.add_argument("--torque", type=float, default=80.0, help="额定扭矩 N·m (默认: 80)")
    parser.add_argument("--lift", type=float, default=180.0, help="额定提水量 L/min (默认: 180)")
    parser.add_argument("--wheel-id", type=str, default="han_dynasty_wheel_001", help="水车ID")
    parser.add_argument("--location", type=str, default="shaanxi_han_ruins", help="水车位置")
    parser.add_argument("--interval", type=int, default=60, help="上报间隔秒 (默认: 60)")
    parser.add_argument("--duration", type=int, default=0, help="模拟时长分钟 (0=无限)")
    parser.add_argument("--speed-factor", type=float, default=1.0, help="转速倍率 (默认: 1.0)")
    parser.add_argument("--torque-factor", type=float, default=1.0, help="扭矩倍率 (默认: 1.0)")
    return parser.parse_args()


if __name__ == "__main__":
    args = parse_args()

    REPORT_INTERVAL = args.interval

    config = WaterWheelConfig(
        wheel_id=args.wheel_id,
        location=args.location,
        nominal_speed=args.speed,
        nominal_torque=args.torque,
        nominal_water_lift=args.lift,
        nominal_level_diff=args.level,
    )

    sim = WaterWheelSimulator(config)
    sim.set_operating_condition(args.speed_factor, args.torque_factor)

    if args.auto or args.duration > 0:
        print(f"启动自动模拟模式 (转速={args.speed}rpm, 水位差={args.level}m, 间隔={args.interval}s)")
        total_minutes = args.duration
        count = 0
        max_count = total_minutes * 60 // args.interval if total_minutes > 0 else -1
        try:
            while max_count < 0 or count < max_count:
                data = sim.generate_reading()
                sim.post_to_backend(data)
                count += 1
                if max_count < 0 or count < max_count:
                    for i in range(REPORT_INTERVAL, 0, -1):
                        print(f"\r  下次上报倒计时: {i}秒 ", end="", flush=True)
                        time.sleep(1)
                    print()
        except KeyboardInterrupt:
            print("\n已停止")
    else:
        interactive_menu()

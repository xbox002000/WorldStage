extends Node3D
## World Runtime Player: plays a file written by runtime/export.py. It decides nothing: positions, hand-offs and
## camera targets all come from the file, and positions follow the same rule as runtime/export.py:sample()
## (a "walk" key moves linearly to the next key, any other pose holds; a carried thing is where its holder is).
##
##   godot --path runtime/godot -- --trace=<file.json> --mode=demo      play, pause, seek back, play on (recordable)
##   godot --headless --path runtime/godot -- --trace=<file.json> --mode=verify --out=<samples.json>

var doc: Dictionary
var bodies := {}      # entity id -> Node3D
var things := {}      # thing id -> Node3D
var cam: Camera3D
var hud: Label
var t := 0.0
var mode := "demo"
var out_path := ""
var script_steps: Array = []   # [kind, arg, label]: play-to, pause-for, seek-to
var step := 0
var hold := 0.0
const FPS := 30.0

func _ready() -> void:
	var args := {}
	for a in OS.get_cmdline_user_args():
		var kv := a.trim_prefix("--").split("=", true, 1)
		args[kv[0]] = kv[1] if kv.size() > 1 else ""
	mode = args.get("mode", "demo")
	out_path = args.get("out", "")
	var f := FileAccess.open(args.get("trace", ""), FileAccess.READ)
	if f == null:
		push_error("no trace file")
		get_tree().quit(2)
		return
	doc = JSON.parse_string(f.get_as_text())
	if mode == "verify":
		_verify()
		return
	_build()
	var d: float = doc["duration"]
	# the demonstration: play, pause, seek back, replay the same moment, play to the end
	script_steps = [["play", d * 0.45, "播放"], ["pause", 1.2, "暫停"], ["seek", d * 0.15, "倒回"],
					["play", d * 0.45, "重播：同一個世界，同一個結果"], ["play", d, "播放"]]

# -- the rule every engine follows ------------------------------------------------------------------------------
func _entity(id: String) -> Dictionary:
	for e in doc["entities"]:
		if e["id"] == id:
			return e
	return {}

func sample(id: String, at: float) -> Array:
	var e := _entity(id)
	if e.is_empty() or e["keys"].is_empty():
		return []
	var keys: Array = e["keys"]
	var cur: Array = keys[0]
	for k in keys:
		if float(k[0]) <= at:
			cur = k
	if cur[5] == "carried" and cur.size() > 6 and str(cur[6]) != "":
		return sample(str(cur[6]), at)
	if at <= float(keys[0][0]):
		return [float(keys[0][2]), float(keys[0][3]), float(keys[0][4])]
	for i in range(keys.size() - 1):
		var a: Array = keys[i]
		var b: Array = keys[i + 1]
		if float(a[0]) <= at and at < float(b[0]):
			if a[5] == "walk" and float(b[0]) > float(a[0]):
				var f := (at - float(a[0])) / (float(b[0]) - float(a[0]))
				return [lerp(float(a[2]), float(b[2]), f), lerp(float(a[3]), float(b[3]), f), float(b[4])]
			return [float(a[2]), float(a[3]), float(a[4])]
	var last: Array = keys[keys.size() - 1]
	return [float(last[2]), float(last[3]), float(last[4])]

func _verify() -> void:
	var samples := {}
	var d: float = doc["duration"]
	var n := int(d / 0.5)
	for i in range(n + 1):
		var at := i * 0.5
		var row := {}
		for e in doc["entities"]:
			var p := sample(e["id"], at)
			if not p.is_empty():
				row[e["id"]] = [snappedf(p[0], 0.0001), snappedf(p[1], 0.0001)]
		samples[str(at)] = row
	var f := FileAccess.open(out_path, FileAccess.WRITE)
	f.store_string(JSON.stringify(samples))
	f.close()
	get_tree().quit(0)

# -- the stage ----------------------------------------------------------------------------------------------------
func _mat(c: Color) -> StandardMaterial3D:
	var m := StandardMaterial3D.new()
	m.albedo_color = c
	m.roughness = 0.85
	return m

func _box(size: Vector3, c: Color) -> MeshInstance3D:
	var mi := MeshInstance3D.new()
	var bm := BoxMesh.new()
	bm.size = size
	mi.mesh = bm
	mi.material_override = _mat(c)
	return mi

func _build() -> void:
	var env := WorldEnvironment.new()
	var e := Environment.new()
	e.background_mode = Environment.BG_COLOR
	e.background_color = Color(0.72, 0.82, 0.9)
	e.ambient_light_color = Color(0.9, 0.9, 0.95)
	e.ambient_light_energy = 0.6
	env.environment = e
	add_child(env)
	var sun := DirectionalLight3D.new()
	sun.rotation_degrees = Vector3(-55, 35, 0)
	sun.shadow_enabled = true
	add_child(sun)
	var colors := {"wall": Color(0.85, 0.83, 0.8), "floor": Color(0.55, 0.7, 0.45), "table": Color(0.55, 0.38, 0.25),
				   "tree": Color(0.3, 0.55, 0.3), "bench": Color(0.6, 0.42, 0.28), "counter": Color(0.5, 0.4, 0.35)}
	var ground := _box(Vector3(40, 0.1, 40), Color(0.62, 0.74, 0.5))
	ground.position = Vector3(6, -0.05, 4)
	add_child(ground)
	for g in doc["geometry"]:
		var h: float = max(0.05, float(g["h"]))
		var b := _box(Vector3(float(g["w"]), h, float(g["d"])), colors.get(g["kind"], Color(0.7, 0.7, 0.7)))
		b.position = Vector3(float(g["x"]), h / 2.0, float(g["y"]))
		b.rotation_degrees.y = -float(g.get("yaw", 0.0))
		add_child(b)
	for ent in doc["entities"]:
		var id: String = ent["id"]
		var node := Node3D.new()
		if ent["kind"] == "thing":
			node.add_child(_box(Vector3(0.22, 0.06, 0.14), Color(0.42, 0.25, 0.15)))
			things[id] = node
		else:
			var c := Color.from_hsv(float(ent.get("hue", 210.0)) / 360.0, 0.55, 0.85)
			if ent["kind"] == "animal":
				var body := _box(Vector3(0.6, 0.3, 0.26), Color(0.85, 0.63, 0.4))
				body.position = Vector3(0, 0.35, 0)
				node.add_child(body)
				var head := _box(Vector3(0.24, 0.22, 0.22), Color(0.85, 0.63, 0.4))
				head.position = Vector3(0.38, 0.5, 0)
				node.add_child(head)
			else:
				var cap := MeshInstance3D.new()
				var cm := CapsuleMesh.new()
				cm.radius = 0.24
				cm.height = 1.45
				cap.mesh = cm
				cap.material_override = _mat(c)
				cap.position = Vector3(0, 0.73, 0)
				node.add_child(cap)
				var head := MeshInstance3D.new()
				var sm := SphereMesh.new()
				sm.radius = 0.17
				sm.height = 0.34
				head.mesh = sm
				head.material_override = _mat(Color(0.96, 0.84, 0.72))
				head.position = Vector3(0, 1.6, 0)
				node.add_child(head)
				var nose := _box(Vector3(0.08, 0.06, 0.06), Color(0.2, 0.2, 0.25))
				nose.position = Vector3(0.18, 1.6, 0)
				node.add_child(nose)
			var label := Label3D.new()
			label.text = ent.get("name", id)
			label.billboard = BaseMaterial3D.BILLBOARD_ENABLED
			label.font_size = 48
			label.position = Vector3(0, 2.05 if ent["kind"] == "person" else 0.95, 0)
			node.add_child(label)
			bodies[id] = node
		add_child(node)
	cam = Camera3D.new()
	cam.fov = 55
	add_child(cam)
	cam.position = Vector3(6, 7, 14)
	cam.look_at(Vector3(6, 0, 4))
	var layer := CanvasLayer.new()
	add_child(layer)
	hud = Label.new()
	hud.position = Vector2(40, 30)
	hud.add_theme_font_size_override("font_size", 26)
	hud.add_theme_color_override("font_color", Color(0.1, 0.1, 0.15))
	layer.add_child(hud)

func _holder_at(id: String, at: float) -> Array:
	var e := _entity(id)
	var cur: Array = e["keys"][0]
	for k in e["keys"]:
		if float(k[0]) <= at:
			cur = k
	return cur

func _place_all() -> void:
	for id in bodies:
		var p := sample(id, t)
		if p.is_empty():
			continue
		bodies[id].position = Vector3(p[0], 0, p[1])
		bodies[id].rotation_degrees.y = -p[2]
		var k := _holder_at(id, t)
		bodies[id].visible = k[5] != "offstage"
	for id in things:
		var k := _holder_at(id, t)
		var p := sample(id, t)
		if p.is_empty():
			continue
		things[id].visible = k[5] != "offstage"
		if k[5] == "carried" and k.size() > 6 and bodies.has(str(k[6])):
			var holder: Node3D = bodies[str(k[6])]
			var animal: bool = _entity(str(k[6]))["kind"] == "animal"
			var off := Vector3(0.52, 0.42, 0) if animal else Vector3(0.1, 0.95, 0.3)
			things[id].position = holder.position + off.rotated(Vector3.UP, holder.rotation.y)
		else:
			things[id].position = Vector3(p[0], 0.04, p[1])

func _camera(delta: float) -> String:
	var target := ""
	var why := "全景"
	for s in doc["camera"]:
		if float(s["start"]) <= t and t <= float(s["end"]):
			target = s["target"]
			why = s["why"]
	# between actions: keep the scene's focus in frame, wide enough to hold everyone around it
	if target == "" and doc.has("focus") and bodies.has(str(doc["focus"])) and bodies[str(doc["focus"])].visible:
		target = str(doc["focus"])
		why = "wide"
	var centre := Vector3.ZERO
	var count := 0
	for id in bodies:
		if bodies[id].visible:
			centre += bodies[id].position
			count += 1
	centre = centre / max(1, count)
	var goal_pos := centre + Vector3(-1.5, 6.5, 8.5)
	var goal_look := centre
	if target != "" and bodies.has(target) and why == "wide":
		var q: Vector3 = bodies[target].position
		goal_look = q.lerp(centre, 0.35) + Vector3(0, 0.4, 0)
		goal_pos = goal_look + Vector3(-2.5, 4.0, 5.5)
	elif target != "" and bodies.has(target):
		var p: Vector3 = bodies[target].position
		goal_pos = p + Vector3(-2.6, 2.4, 3.4)
		goal_look = p + Vector3(0, 0.8, 0)
	cam.position = cam.position.lerp(goal_pos, clamp(delta * 3.0, 0.0, 1.0))
	cam.look_at(goal_look)
	if target == "":
		return "全景"
	var name := (bodies[target].get_child(bodies[target].get_child_count() - 1) as Label3D).text
	return name + ("（遠）" if why == "wide" else "")

func _process(_delta: float) -> void:
	if mode != "demo" or doc.is_empty():
		return
	var dt := 1.0 / FPS
	var label := ""
	if step >= script_steps.size():
		get_tree().quit(0)
		return
	var s: Array = script_steps[step]
	label = s[2]
	if s[0] == "play":
		t += dt
		if t >= float(s[1]):
			step += 1
	elif s[0] == "pause":
		hold += dt
		if hold >= float(s[1]):
			hold = 0.0
			step += 1
	elif s[0] == "seek":
		t = float(s[1])
		step += 1
	_place_all()
	var who := _camera(dt)
	var held := ""
	for id in things:
		var k := _holder_at(id, t)
		if k[5] == "carried" and k.size() > 6:
			held += "%s → %s  " % [id, k[6]]
	hud.text = "%s   t = %.1f s   鏡頭跟著：%s\n%s" % [label, t, who, held]

# 参考运动格式

JSON 不含图片、密钥或模型 URL。示例见 `examples/reference-attack.json`。

```json
{
  "format": "rig-motion-reference.v1",
  "space": "x-right,y-up,fixed-height",
  "name": "自己的动作",
  "provenance": "说明原始素材与处理方法",
  "frames": [
    {"time": 0.0, "joints": {"pelvis": [0, 0.5]}, "contacts": {"l": true, "r": true}}
  ]
}
```

上面的关节/帧只用于简化展示；**实际必须有 4–240 帧，每帧包含以下全部关节**：

```text
pelvis chest neck head
l_shoulder l_elbow l_wrist
r_shoulder r_elbow r_wrist
l_hip l_knee l_ankle l_toe
r_hip r_knee r_ankle r_toe
```

坐标为 X 向右、Y 向上、固定初始高度单位。`time` 是秒，必须严格递增，总时长至少 0.1 秒，最大时间戳30秒。不要把每帧的身高单独缩成1，不要把 hips-centered 3D 坐标误当成带全局位移的运动。

`contacts.l/r` 表示对应采样点的脚接触阶段。省略时不锁定这一侧。人体自动检测器产生的接触是启发式标记，需要人工复核；本版没有接触区间图形编辑器，可修改 JSON 后重新导入。

校准帧由 UI 的索引指定。从源骨架提取局部角度并展开 ±π，再相对校准帧转移变化到目标 bind pose。骨长始终来自目标角色，不来自视频屏幕像素。根位移按一次固定尺度转移，原地模式只移除水平根运动、保留垂直运动。

平滑窗口1/3/5对应角度和根轨迹上的局部均值。它不会修正严重错误的左右映射或遮挡跳点。原地转身和强透视缩短不在二维版本保证范围内。

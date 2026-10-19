# 技术依据与外部组件

访问核对日期：2026-10-19。以下是实现接口的主来源，非项目效果背书。

## Google MediaPipe Tasks

- Pose Landmarker Python 指南： https://developers.google.com/edge/mediapipe/solutions/vision/pose_landmarker/python
- 模型与人体关键点定义： https://developers.google.com/edge/mediapipe/solutions/vision/pose_landmarker/index
- 官方 Lite 模型下载（用户自行下载，不包含在此项目）： https://storage.googleapis.com/mediapipe-models/pose_landmarker/pose_landmarker_lite/float16/latest/pose_landmarker_lite.task

使用 `PoseLandmarker.create_from_options`、`RunningMode.VIDEO`、RGB `mp.Image`、递增时间戳 `detect_for_video`。关键点坐标按图像宽高归一化，恢复同尺度像素后再建立固定二维标定。3D world landmarks 以髋部中点为原点，本项目不把它当成全局运动捕捉。

模型/依赖遵循各自许可。代码未包含外部模型权重；未在交付环境执行真实 MediaPipe 推理。用户输入视频仅在本机分析，不上传外部图片或视频服务。

## Pillow

- AffineTransform / 逆采样矩阵： https://pillow.readthedocs.io/en/stable/reference/ImageTransform.html
- Image 接口： https://pillow.readthedocs.io/en/stable/reference/Image.html

固定 PNG 使用 RGBA 与最近邻仿射采样。预览 GIF 为索引色输出，原始 Alpha PNG 是素材来源。

## 数学参考

`lab/math2d.py` 改编自本次对话交付的 `SpriteForge-motion-core-reference.zip`：解析两骨 IK、Hermite 插值、连续支撑脚轨迹、角度展开、仿射变换。并未引入一个训练好的动作生成模型。

内置14件守卫素材由 `lab/demo.py` 原创程序绘制；内置参考轨迹由 `lab/reference.py` 合成。没有真人动作样本或用户私有角色被打包为示例。

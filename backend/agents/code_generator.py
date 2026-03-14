"""
H5 游戏代码生成 Agent（效果注册表架构）
拆分为 data.js + effects.js + scenes.js + main.js（模板），
每步 LLM 调用输出 < 600 行，从根本上解决截断问题。
"""
from __future__ import annotations

import logging
import re
from typing import AsyncGenerator

from langchain_openai import ChatOpenAI

from config import settings
from graph.state import GameDesignState

logger = logging.getLogger(__name__)

# ──────────────────────────────────────────────────────────────────────────────
# 固定模板（无需 LLM 生成）
# ──────────────────────────────────────────────────────────────────────────────

_INDEX_HTML_TEMPLATE = """<!DOCTYPE html>
<html>
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width,initial-scale=1.0,maximum-scale=1.0,user-scalable=no">
<title>{game_title}</title>
<link rel="stylesheet" href="style.css">
<script src="https://cdn.jsdelivr.net/npm/phaser@3.88.2/dist/phaser.min.js"></script>
</head>
<body>
<script src="data.js"></script>
<script src="effects.js"></script>
<script src="scenes.js"></script>
<script src="main.js"></script>
</body>
</html>"""

_STYLE_CSS = """* { margin:0; padding:0; }
body { background:#000; overflow:hidden; display:flex; justify-content:center; align-items:center; height:100vh; }
"""

_MAIN_JS_TEMPLATE = """const config = {{
  type: Phaser.AUTO,
  width: 1920,
  height: 1080,
  scale: {{ mode: Phaser.Scale.FIT, autoCenter: Phaser.Scale.CENTER_BOTH }},
  physics: {{ default: 'arcade', arcade: {{ gravity: {{ y: 0 }}, debug: false }} }},
  scene: [BootScene, MenuScene, GameScene],
  backgroundColor: '#000000'
}};
const game = new Phaser.Game(config);
"""

# ──────────────────────────────────────────────────────────────────────────────
# Step 1 Prompt: data.js — 游戏数据层（不变）
# ──────────────────────────────────────────────────────────────────────────────

_DATA_SYSTEM_PROMPT = """你是资深 H5 游戏工程师，根据玩法文档生成**数据层 data.js**。

## 输出规范
- 只输出纯 JavaScript 源码，无 markdown/HTML/说明
- 图片 URL 统一以 `/static/` 开头
- 数值、名称、效果严格按玩法文档，不遗漏

## 输出内容（按顺序）

### 1. 全局常量
```js
const GAME_TITLE = '游戏名称';
const THEME_COLOR = 0xRRGGBB;
const PLAYER_HP = N;
const PLAYER_IMG = 'char_protagonist_sample';
```

### 2. 卡牌池（10张，含 Lv1-Lv3 升级数值）
```js
const CARDS = [
  { id:'xxx', name:'名称', effect:'effect_type', color:0xRRGGBB,
    levels: [
      { ...Lv1数值字段, desc:'Lv1描述' },
      { ...Lv2数值字段, desc:'Lv2描述' },
      { ...Lv3数值字段, desc:'Lv3描述' }
    ]},
];
```
每张卡的 `levels` 数组中，每级的数值字段根据该卡效果自定义（如 dmg/radius/interval/chance），但必须包含 `desc` 字段。

### 3. 羁绊（5-7个）
```js
const SYNERGIES = [
  { id:'xxx', name:'名称', requiredCards:['card_a','card_b'],
    effect:'描述', bonusValue:N, vfxColor:0xRRGGBB },
];
```

### 4. 敌人 + Boss（size 为游戏内显示尺寸，须足够大以便辨认）
```js
const ENEMIES = [
  { name:'名称', hp:N, atk:N, speed:N, color:0xRRGGBB, img:'enemy_xxx', size:112, exp:N },
];
const BOSS_DATA = { name:'Boss名', hp:N, atk:N, speed:N, color:0xRRGGBB, img:'enemy_xxx', size:220, exp:N };
```
ENEMIES 每项 size 建议 100~128，BOSS_DATA 的 size 建议 200~260（PC 端占比约 9~12% / 18~24%）。

### 5. 全局工具函数（必须全部包含，不可省略）

```js
function hasUsableTexture(scene, key) {
  return scene.textures.exists(key)
    && scene.textures.get(key).source
    && scene.textures.get(key).source[0]
    && scene.textures.get(key).source[0].width > 4;
}

// 参数顺序：makeFallbackTexture(scene, key, color, w, h) — 第3个是 color，第4、5 是宽高
function makeFallbackTexture(scene, key, color, w, h) {
  if (hasUsableTexture(scene, key)) return;
  if (typeof color === 'number' && color < 2000 && typeof w === 'number' && w > 0xFFFF) {
    var _t = color; color = w; w = _t;
  }
  const g = scene.make.graphics({ add: false });
  g.fillStyle(color, 1).fillRoundedRect(0, 0, w, h, 14);
  g.lineStyle(3, 0xffffff, 0.45).strokeRoundedRect(3, 3, w-6, h-6, 12);
  const lc = Phaser.Display.Color.IntegerToColor(color).lighten(35).color;
  g.fillStyle(lc, 1).fillCircle(w/2, h*0.28, w*0.2);
  g.generateTexture(key, w, h);
  g.destroy();
}

// removeBackground: 完整实现（必须照抄，不可省略或改写）
// tolerance 控制抠图强度：较小值(20~24)抠图更保守、减少边缘裁切；较大值(35~45)更激进
function removeBackground(scene, key, tolerance) {
  tolerance = tolerance || 34;
  if (!scene.textures.exists(key)) return;
  const src = scene.textures.get(key).source[0];
  const w = src.width, h = src.height;
  if (w < 4 || h < 4) return;
  const cv = document.createElement('canvas');
  cv.width = w; cv.height = h;
  const ctx = cv.getContext('2d');
  try {
    ctx.drawImage(src.image || src.canvas, 0, 0);
    const imgData = ctx.getImageData(0, 0, w, h);
    const d = imgData.data;
    const sampleAt = (px, py) => {
      const idx = (py * w + px) * 4;
      return [d[idx], d[idx+1], d[idx+2], d[idx+3]];
    };
    const probes = [
      sampleAt(0,0), sampleAt(w-1,0), sampleAt(0,h-1), sampleAt(w-1,h-1),
      sampleAt(Math.floor(w/2),0), sampleAt(0,Math.floor(h/2)),
      sampleAt(w-1,Math.floor(h/2)), sampleAt(Math.floor(w/2),h-1)
    ].filter(c => c[3] > 200);
    if (probes.length === 0) return;
    const bgColors = [probes[0].slice(0,3)];
    for (const c of probes.slice(1)) {
      const rgb = c.slice(0,3);
      const similar = bgColors.some(b =>
        Math.abs(rgb[0]-b[0]) < 26 && Math.abs(rgb[1]-b[1]) < 26 && Math.abs(rgb[2]-b[2]) < 26
      );
      if (!similar) bgColors.push(rgb);
    }
    const tol2 = tolerance * tolerance;
    for (let i = 0; i < d.length; i += 4) {
      if (d[i+3] < 10) continue;
      for (const bg of bgColors) {
        const dr=d[i]-bg[0], dg=d[i+1]-bg[1], db=d[i+2]-bg[2];
        if (dr*dr + dg*dg + db*db < tol2) { d[i+3]=0; break; }
      }
    }
    ctx.putImageData(imgData, 0, 0);
    scene.textures.remove(key);
    scene.textures.addCanvas(key, cv);
  } catch(e) { console.warn('removeBackground failed:', key, e); }
}

function makeCard(scene, x, y, card, lvl) { ... }         // 仅展示图片，不叠加任何文字
function floatText(scene, x, y, msg, color) { ... }       // 飘字动画
function makeHPBar(scene, x, y, w, h, maxVal, fillColor) { ... } // 状态条
```

**removeBackground**：已给出完整实现，照抄即可。**makeCard**：**只展示图片**。有 `card_{id}` 纹理时，仅用 add.image + setDisplaySize(400,600) 展示该纹理，**不添加** card.name、card.desc、Lv、描边、按钮等任何叠加内容；无纹理时用 makeFallbackTexture 后同样仅展示占位图。卡牌图已含完整设计，展示尺寸 400×600 或以上。

## 禁止
本文件只输出 data.js 内容。不输出 Scene 类、EFFECT_REGISTRY、Phaser.Game config、HTML/CSS/markdown。"""


_DATA_USER_TEMPLATE = """根据以下 GDD 生成 data.js 文件。

## 游戏概要
{summary}

## ★ 玩法设计文档（卡牌/羁绊/敌人/数值 全部从这里提取）
{sec_gameplay}

## 世界观（命名风格、色调）
{sec_worldview}

## 已生成美术资源（key → URL，用于 ENEMIES/BOSS_DATA 的 img 字段匹配）
{art_manifest}

---
请输出完整的 data.js 文件内容（纯 JavaScript，无 markdown 包裹）。"""

# ──────────────────────────────────────────────────────────────────────────────
# Step 2 Prompt: effects.js — 效果注册表
# ──────────────────────────────────────────────────────────────────────────────

_EFFECTS_SYSTEM_PROMPT = """你是资深 H5 游戏工程师，根据玩法文档生成**效果注册表 effects.js**。

## 前置
data.js 已加载，可直接使用：`CARDS`（10张）、`SYNERGIES`、`ENEMIES`、`BOSS_DATA`，以及 `hasUsableTexture`、`makeFallbackTexture`、`floatText`、`makeHPBar`。不要重复定义。

## 输出规范
- 只输出纯 JavaScript，无 markdown/HTML
- 每张卡效果逐一完整实现，禁止 TODO 占位

## 输出内容

### 1. EFFECT_REGISTRY —— 卡牌效果注册表

每张卡以其 `id` 为 key，注册到 `EFFECT_REGISTRY` 对象中。每张卡可以注册以下钩子函数（根据其效果类型选择需要的钩子）：

| 钩子 | 调用时机 | 参数 |
|------|---------|------|
| `onActivate(scene, lvlData)` | 首次获得或升级时 | 用于创建持续性效果（如环绕物体） |
| `onTick(scene, dt, lvlData)` | 每帧 update() 调用 | 用于持续性效果（轨道旋转、DOT 检测） |
| `onBulletHit(scene, bullet, enemy, lvlData)` | 子弹命中敌人时 | 用于命中触发效果（分裂、腐蚀） |
| `onEnemyKill(scene, enemy, lvlData)` | 敌人被击杀时 | 用于击杀触发（治疗、爆炸） |
| `onPlayerDamaged(scene, rawDmg, lvlData)` | 玩家受伤时 | 用于受伤触发（反弹、护盾） |
| `onPlayerDeath(scene, lvlData)` | 玩家死亡时 | 用于死亡触发（自爆） |
| `onDash(scene, fromX, fromY, toX, toY, lvlData)` | 闪避/冲刺时 | 用于位移触发（火焰路径） |
| `onExpPickup(scene, orb, lvlData)` | 拾取经验时 | 用于拾取触发（随机雷击） |
| `getStatModifiers(lvlData)` | 获取永久属性修改 | 返回 {atkMul, spdMul, rangeMul, sizeMul, maxHpMul} |

示例：
```js
const EFFECT_REGISTRY = {
  split_bullet: {
    onBulletHit(scene, bullet, enemy, lvlData) {
      const count = lvlData.splitCount || 2;
      const dmgRatio = lvlData.dmgRatio || 0.4;
      for (let i = 0; i < count; i++) {
        const angle = bullet.rotation + (i - (count-1)/2) * 0.5;
        scene.spawnBullet(enemy.x, enemy.y, angle, bullet.dmg * dmgRatio, true);
      }
    }
  },
  electric_shield: {
    onActivate(scene, lvlData) {
      // 创建/更新环绕电磁球数量
    },
    onTick(scene, dt, lvlData) {
      // 旋转电磁球 + 对接触敌人造成伤害
    }
  },
  // ... 10 张卡全部注册
};
```

**每张卡的效果必须逐一完整实现**，不得用通用模板或 TODO 占位。
钩子函数中通过 `scene.xxx` 访问 GameScene 的属性（如 `scene.player`, `scene.ownedCards`, `scene.enemyGroup` 等）。
数值从 `lvlData` 参数读取（即 `CARDS[i].levels[lvl-1]`）。

### 2. SYNERGY_REGISTRY —— 羁绊效果注册表

```js
const SYNERGY_REGISTRY = {
  synergy_id: {
    onActivate(scene) {
      // 羁绊首次激活时的效果
    },
    onTick(scene, dt) {
      // 羁绊持续效果（可选）
    }
  },
  // ... 每个羁绊
};
```

### 3. 辅助分发函数

```js
function dispatchEffect(hookName, scene, ...args) {
  for (const [cardId, lvl] of scene.ownedCards) {
    const reg = EFFECT_REGISTRY[cardId];
    if (reg && reg[hookName]) {
      const card = CARDS.find(c => c.id === cardId);
      const lvlData = card ? card.levels[Math.min(lvl, card.levels.length) - 1] : {};
      reg[hookName](scene, ...args, lvlData);
    }
  }
}

function dispatchSynergyTick(scene, dt) {
  for (const syn of scene.activeSynergies || []) {
    const reg = SYNERGY_REGISTRY[syn.id];
    if (reg && reg.onTick) reg.onTick(scene, dt);
  }
}
```

## 禁止
只输出 effects.js：EFFECT_REGISTRY、SYNERGY_REGISTRY、dispatchEffect、dispatchSynergyTick。不输出 Scene、CARDS/ENEMIES、config、HTML/markdown。"""


_EFFECTS_USER_TEMPLATE = """根据以下 GDD 生成 effects.js 文件（效果注册表）。

## 游戏概要
{summary}

## ★ 玩法设计文档（每张卡的效果从这里提取）
{sec_gameplay}

## data.js 导出的函数签名（调用时必须严格匹配参数顺序和个数）
{data_js_signatures}

## data.js 内容（已加载，可直接使用其中的变量和函数）
```javascript
{data_js}
```

---
请输出完整的 effects.js 文件内容（纯 JavaScript，无 markdown 包裹）。
必须包含 EFFECT_REGISTRY（10张卡）、SYNERGY_REGISTRY（所有羁绊）、dispatchEffect、dispatchSynergyTick。"""

# ──────────────────────────────────────────────────────────────────────────────
# Step 3 Prompt: scenes.js — 场景层（核心骨架）
# ──────────────────────────────────────────────────────────────────────────────

_SCENES_SYSTEM_PROMPT = """你是资深 H5 游戏工程师，根据玩法文档生成**场景层 scenes.js**。

## 前置
data.js 提供：GAME_TITLE、THEME_COLOR、PLAYER_HP、PLAYER_IMG、CARDS、SYNERGIES、ENEMIES、BOSS_DATA，以及 hasUsableTexture、makeFallbackTexture(scene,key,color,w,h)、removeBackground、makeCard、floatText、makeHPBar。
effects.js 提供：EFFECT_REGISTRY、SYNERGY_REGISTRY、dispatchEffect、dispatchSynergyTick。不要重复定义。

## 关键约定（易错点）
1. **卡牌效果**：update 中写 `dispatchEffect('onTick', this, dt)`，禁止自创 `updateCardEffects` 等
2. **键盘**：addKeys 的 key 是 left/right/up/down/arrowLeft，update 中用 `this.keys.left` 而非 `keys.A`；用方向键需先 `createCursorKeys()` 得到 `this.cursors`
3. **makeFallbackTexture**：参数顺序 (scene, key, color, w, h)，第3个是 color

## 输出规范
- 纯 JavaScript，无 markdown/HTML
- 分辨率 1920×1080，场景名 'Boot'、'Menu'、'Game'
- 优先保证完整，GameScene 必须包含 create、update、takeDamage、updateHUD、showGameOver、showVictory

## 效果分发规则（最重要！）

GameScene 中**不要硬编码任何卡牌特定逻辑**。在以下时机调用 dispatchEffect：

```js
// 子弹命中敌人时
onBulletHitEnemy(bullet, enemy) {
  this.damageEnemy(enemy, bullet.dmg);
  dispatchEffect('onBulletHit', this, bullet, enemy);
}

// update() 每帧
update(time, delta) {
  const dt = delta / 1000;
  if (this.isChoosingCard) {
    // 选卡期间暂停战斗逻辑，玩家不会受到攻击
    return;
  }
  // ... 移动、碰撞等通用逻辑 ...
  dispatchEffect('onTick', this, dt);
  dispatchSynergyTick(this, dt);
}

// 敌人被击杀时
onEnemyDeath(enemy) {
  // ... 经验掉落等 ...
  dispatchEffect('onEnemyKill', this, enemy);
}

// 玩家受伤时
takeDamage(rawDmg) {
  if (this.isChoosingCard) {
    // 选卡期间不结算伤害
    return;
  }
  // ... 扣血逻辑 ...
  dispatchEffect('onPlayerDamaged', this, rawDmg);
}

// 闪避/冲刺时
performDash() {
  // ... 位移逻辑 ...
  dispatchEffect('onDash', this, fromX, fromY, toX, toY);
}

// 拾取经验时
onPickupExp(player, orb) {
  // ... 经验累加 ...
  dispatchEffect('onExpPickup', this, orb);
}

// 玩家死亡时
onPlayerDeath() {
  dispatchEffect('onPlayerDeath', this);
  // ... 结算画面 ...
}

// 获得/升级卡牌后
onCardObtained(cardId, newLvl) {
  const card = CARDS.find(c => c.id === cardId);
  const lvlData = card.levels[newLvl - 1];
  const reg = EFFECT_REGISTRY[cardId];
  if (reg && reg.onActivate) reg.onActivate(this, lvlData);
  // 应用属性修改器
  if (reg && reg.getStatModifiers) {
    const mods = reg.getStatModifiers(lvlData);
    // 更新玩家属性...
  }
  this.checkSynergies();
}
```

## 你必须输出的内容

### BootScene
- `preload()`：加载进度条 + 逐行加载所有美术资源
- `create()`：
  - 调用 `makeFallbackTexture(this, key, color, w, h)` 为加载失败的纹理创建占位 ← **第3参数是颜色，不是宽度！**
  - 调用 `removeBackground(this, key)` 清除角色/敌人背景
  - 然后 `this.scene.start('Menu')`

### MenuScene
- 背景图 + 游戏标题 + 副标题 + 开始按钮
- **界面须优美**：按钮用 setStrokeStyle 描边、圆角矩形或 setScale  hover 动效，标题用 stroke/strokeThickness 增加层次感，避免纯色方块

### GameScene
先判断游戏类型（实时动作/回合制/跑酷），然后实现：

1. `create()` —— 初始化玩家、敌人组、子弹组、键盘输入、HUD
   - **玩家精灵**：`this.player.setDisplaySize(136, 136)` 或 128~144 范围（PC 端占比约 12~13%）
   - **敌人**：使用 data.js 中 ENEMIES 的 size 字段做 setDisplaySize，若 data 未定义则用 112
   - **Boss**：使用 BOSS_DATA 的 size 做 setDisplaySize，建议 200~260
   - **背景虚化**：背景 tileSprite（this.bg）创建后调用 `this.bg.postFX.addBlur(6)` 虚化背景，突出主角和怪物
   - `this.ownedCards = new Map()` —— 持有卡牌（cardId → level）
   - `this.activeSynergies = []` —— 已激活羁绊列表
2. `update(time, delta)` —— 帧循环（移动 + 碰撞 + dispatchEffect('onTick')）
3. 玩家移动（WASD / 方向键）
4. 玩家射击 / 自动攻击
5. `spawnBullet(x, y, angle, dmg, isSplit)` —— 供 effects.js 中的分裂效果调用
6. 碰撞回调 → dispatchEffect 分发
7. 敌人 AI + 波次刷新 + Boss 登场
8. 经验 / 升级系统 → 触发选卡弹窗
9. 选卡弹窗（3选1）：**选卡期间游戏必须暂停**（update 不执行敌人移动/碰撞/伤害，玩家不受攻击），弹窗出现时设 `this.isChoosingCard = true`，选完再恢复。卡牌**只展示图片**（调用 makeCard 即可），不叠加 card.name、desc、Lv 等文字；每张 400×600 或以上，选卡区域约占屏幕 50%；pointerover 时 setScale(1.05) 作为点击反馈
10. 羁绊检测：`checkSynergies()` → 更新 `this.activeSynergies`
11. HUD：血条/经验条用圆角或渐变填充，与主题色协调
12. 胜/负判定 + 一键重玩：结算界面有遮罩、标题描边、按钮 hover 反馈

## UI 与比例
按钮/选卡：圆角、描边、hover 时 setScale(1.05)。弹窗：半透明遮罩、居中。主角 128~144px，敌人 100~128px，Boss 200~260px。**选卡 UI**：卡牌为游戏核心，每张卡 400×600 以上，选卡区域占屏幕约 50%；选卡时游戏暂停（isChoosingCard 为 true 时 update 跳过战斗逻辑）。

## 禁止
只输出 BootScene/MenuScene/GameScene 三个类。不输出 CARDS/SYNERGIES/ENEMIES、EFFECT_REGISTRY/SYNERGY_REGISTRY、工具函数、new Phaser.Game、HTML/markdown。"""


_SCENES_USER_TEMPLATE = """根据以下 GDD 生成 scenes.js 文件。

## 游戏概要
{summary}

## ★ 玩法设计文档（核心循环和操控方式由此决定）
{sec_gameplay}

## 世界观
{sec_worldview}

## 美术资源清单（BootScene.preload() 中逐行加载）
{art_manifest}

## data.js 导出的函数签名（调用时必须严格匹配参数顺序和个数）
{data_js_signatures}

## data.js 内容（已加载，可直接使用）
```javascript
{data_js}
```

## effects.js 内容（已加载，通过 dispatchEffect 调用）
```javascript
{effects_js}
```

---
请输出完整的 scenes.js 文件内容（纯 JavaScript，无 markdown 包裹）。
包含 BootScene、MenuScene、GameScene 三个类。
不要包含 `new Phaser.Game(config)`。"""

# ──────────────────────────────────────────────────────────────────────────────
# 续写 Prompt（scenes.js 截断后自动续写）
# ──────────────────────────────────────────────────────────────────────────────

_SCENES_CONTINUE_SYSTEM = """你是资深 H5 游戏工程师。scenes.js 在生成过程中被截断了，你的任务是**从断点处继续写完剩余代码**。

## 铁律
1. **只输出续写部分的纯 JavaScript 代码**，不加任何 markdown 标记
2. 从提供的代码尾部之后继续
3. 如果最后一行是不完整的语句，先补全该语句
4. 确保所有 class 和函数的大括号正确闭合
5. **不要重复**已有的类定义和方法
6. 不要输出 `new Phaser.Game(config)`

## 前置条件（全局可用，不要重新定义）
- data.js: GAME_TITLE, THEME_COLOR, PLAYER_HP, CARDS, SYNERGIES, ENEMIES, BOSS_DATA, makeFallbackTexture, floatText, makeHPBar 等
- effects.js: EFFECT_REGISTRY, SYNERGY_REGISTRY, dispatchEffect, dispatchSynergyTick"""

_SCENES_CONTINUE_USER = """scenes.js 生成到一半被截断了。以下是已生成代码的**尾部（最后 150 行）**，请从断点处继续写完。

## 已生成代码尾部
```javascript
{tail_code}
```

## 截断诊断
{missing_info}

## 要求
1. **只输出续写部分**，不要重复上面已有的代码
2. 确保 GameScene 类中包含完整的 update()、updateHUD()、takeDamage()、showGameOver()、showVictory() 方法
3. 确保所有 class 的大括号正确闭合
4. 不要输出 markdown 标记"""


# ──────────────────────────────────────────────────────────────────────────────
# 辅助函数
# ──────────────────────────────────────────────────────────────────────────────

def _build_summary(state: GameDesignState) -> str:
    sr = state.get("structured_req") or {}
    parts = []
    if sr.get("theme"):       parts.append(f"主题：{sr['theme']}")
    if sr.get("protagonist"): parts.append(f"主角：{sr['protagonist']}")
    if sr.get("core_mechanic"): parts.append(f"核心机制：{sr['core_mechanic']}")
    return "；".join(parts) if parts else "Roguelike 卡牌战斗游戏"


_INVALID_MARKERS = ("以此类推", "同上", "每类均有", "*(", "等）", "以下类推")


def _clean_art_key(raw: str) -> str:
    key = raw.strip().strip("`").strip()
    key = re.sub(r"[^\w\-]", "_", key)
    key = re.sub(r"_+", "_", key).strip("_")
    return key


def _build_art_manifest(state: GameDesignState) -> str:
    """构建美术资源清单，格式：key → /static/art/{sid}/{filename}.ext"""
    art_assets: dict = state.get("art_assets") or {}
    art_samples: dict = state.get("art_samples") or {}
    all_art = {**art_samples, **art_assets}

    if not all_art:
        return "（尚未生成美术资源，所有图片用程序化图形占位）"

    lines: list[str] = []
    for raw_fname, url_path in all_art.items():
        if any(m in raw_fname for m in _INVALID_MARKERS):
            continue
        clean_key = _clean_art_key(raw_fname)
        if not clean_key:
            continue
        clean_url = re.sub(r"^https?://[^/]+", "", str(url_path))
        clean_url = clean_url.replace("`", "%60")
        lines.append(f"  {clean_key} → {clean_url}")

    return "\n".join(lines) if lines else "（美术资源清单为空，请用程序化图形占位）"


def _extract_js(text: str) -> str:
    """从 LLM 输出中提取 JS（兼容带 markdown 代码块的情况）。"""
    for pattern in [r"```(?:javascript|js)\s*([\s\S]+?)```", r"```\s*([\s\S]+?)```"]:
        m = re.search(pattern, text)
        if m:
            return m.group(1).strip()
    return text.strip()


def _extract_function_signatures(js_code: str) -> str:
    """从 JS 代码中提取所有顶层 function 签名，返回接口契约文本。"""
    pattern = r"^function\s+(\w+)\s*\(([^)]*)\)"
    sigs: list[str] = []
    for m in re.finditer(pattern, js_code, re.MULTILINE):
        name, params = m.group(1), m.group(2).strip()
        sigs.append(f"  function {name}({params})")
    return "\n".join(sigs) if sigs else "(未检测到函数签名)"


def _validate_cross_file_calls(
    data_js: str, effects_js: str, scenes_js: str,
) -> list[str]:
    """校验 effects.js/scenes.js 对 data.js 函数的调用参数个数是否匹配。"""
    def_pattern = r"^function\s+(\w+)\s*\(([^)]*)\)"
    definitions: dict[str, int] = {}
    for m in re.finditer(def_pattern, data_js, re.MULTILINE):
        name = m.group(1)
        params = [p.strip() for p in m.group(2).split(",") if p.strip()]
        definitions[name] = len(params)

    warnings: list[str] = []
    for fname, code in [("effects.js", effects_js), ("scenes.js", scenes_js)]:
        for func_name, expected_count in definitions.items():
            call_pattern = rf"(?<!\w){func_name}\s*\(([^)]*)\)"
            for cm in re.finditer(call_pattern, code):
                raw_args = cm.group(1).strip()
                if not raw_args:
                    arg_count = 0
                else:
                    depth = 0
                    arg_count = 1
                    for ch in raw_args:
                        if ch in "([{":
                            depth += 1
                        elif ch in ")]}":
                            depth -= 1
                        elif ch == "," and depth == 0:
                            arg_count += 1
                if arg_count != expected_count:
                    warnings.append(
                        f"{fname}: {func_name}() 期望 {expected_count} 个参数，"
                        f"实际传了 {arg_count} 个"
                    )
    return warnings


def _is_scenes_js_complete(js_code: str) -> tuple[bool, str]:
    """检查 scenes.js 是否完整。返回 (is_complete, missing_description)。"""
    if not js_code.strip():
        return False, "文件为空"

    missing: list[str] = []

    if "class BootScene" not in js_code:
        missing.append("缺少 BootScene 类")
    if "class MenuScene" not in js_code:
        missing.append("缺少 MenuScene 类")
    if "class GameScene" not in js_code:
        missing.append("缺少 GameScene 类")

    open_b = js_code.count("{")
    close_b = js_code.count("}")
    if open_b > close_b + 1:
        missing.append(f"大括号未闭合（'{{' 多 {open_b - close_b} 个）")

    if "class GameScene" in js_code:
        game_section = js_code[js_code.index("class GameScene"):]
        for method in ["update(", "takeDamage", "showGameOver", "showVictory"]:
            if method not in game_section:
                missing.append(f"GameScene 缺少 {method.rstrip('(')}()")

    if missing:
        return False, "；".join(missing)
    return True, ""


def assemble_full_html(game_title: str, data_js: str, effects_js: str, scenes_js: str, main_js: str) -> str:
    """将所有 JS 内联拼成完整 HTML（用于 game_code 字段向后兼容）。"""
    return f"""<!DOCTYPE html>
<html>
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width,initial-scale=1.0,maximum-scale=1.0,user-scalable=no">
<title>{game_title}</title>
<style>* {{ margin:0; padding:0; }} body {{ background:#000; overflow:hidden; display:flex; justify-content:center; align-items:center; height:100vh; }}</style>
<script src="https://cdn.jsdelivr.net/npm/phaser@3.88.2/dist/phaser.min.js"></script>
</head>
<body>
<script>
// ═══ DATA LAYER ═══
{data_js}
</script>
<script>
// ═══ EFFECTS REGISTRY ═══
{effects_js}
</script>
<script>
// ═══ SCENES ═══
{scenes_js}
</script>
<script>
// ═══ GAME INIT ═══
{main_js}
</script>
</body>
</html>"""


def _get_code_llm():
    """创建代码生成用的 LLM 实例。"""
    code_model = settings.CODE_MODEL
    extra_kwargs: dict = {}
    if code_model.startswith("anthropic/"):
        extra_kwargs["max_tokens"] = 200000

    extra_headers = {}
    if settings.is_openrouter:
        if settings.OR_SITE_URL:
            extra_headers["HTTP-Referer"] = settings.OR_SITE_URL
        if settings.OR_SITE_NAME:
            extra_headers["X-Title"] = settings.OR_SITE_NAME

    return ChatOpenAI(
        model=code_model,
        api_key=settings.OPENAI_API_KEY,
        base_url=settings.OPENAI_BASE_URL,
        streaming=True,
        temperature=0.1,
        request_timeout=600,
        max_retries=1,
        default_headers=extra_headers or None,
        **extra_kwargs,
    ), code_model


async def _stream_llm(llm, messages) -> AsyncGenerator[tuple[str, str], None]:
    """流式调用 LLM，yield (event_type, content) 元组。"""
    async for chunk in llm.astream(messages):
        raw = chunk.content
        if isinstance(raw, list):
            token = "".join(
                part.get("text", "") if isinstance(part, dict) else str(part)
                for part in raw
            )
        else:
            token = raw or ""
        if token:
            yield ("token", token)


# ──────────────────────────────────────────────────────────────────────────────
# 主函数（3 步 LLM 生成 SSE 流）
# ──────────────────────────────────────────────────────────────────────────────

async def generate_game_code_stream(
    state: GameDesignState,
) -> AsyncGenerator[dict, None]:
    """
    分三步生成游戏代码（data.js + effects.js + scenes.js），yield SSE 事件。
    """
    sec_gameplay  = (state.get("sec_gameplay")  or "").strip()
    sec_worldview = (state.get("sec_worldview") or "").strip()

    if not sec_gameplay:
        fallback = (state.get("final_doc") or "").strip()
        if not fallback:
            yield {"type": "error", "message": "尚未生成游戏设计文档，请先完成 GDD 生成流程"}
            return
        sec_gameplay = fallback[:6000]

    summary      = _build_summary(state)
    art_manifest = _build_art_manifest(state)

    llm, code_model = _get_code_llm()
    logger.info("代码生成使用模型：%s", code_model)

    # ── Step 1: 生成 data.js ────────────────────────────────────────
    yield {"type": "progress", "message": f"[1/3] 正在生成数据层 (data.js)，模型: {code_model}..."}

    data_messages = [
        {"role": "system", "content": _DATA_SYSTEM_PROMPT},
        {"role": "user",   "content": _DATA_USER_TEMPLATE.format(
            summary       = summary,
            sec_gameplay  = sec_gameplay[:8000]  or "（暂无）",
            sec_worldview = sec_worldview[:3000] or "（暂无）",
            art_manifest  = art_manifest,
        )},
    ]

    data_js_text = ""
    data_token_count = 0
    try:
        async for _, content in _stream_llm(llm, data_messages):
            data_js_text += content
            data_token_count += len(content)
            yield {"type": "token", "text": content}
            if data_token_count % 300 < len(content):
                yield {"type": "progress", "message": f"[1/3] data.js 生成中... {data_token_count} 字符"}
    except Exception as exc:
        logger.exception("data.js 生成失败：%s", exc)
        yield {"type": "error", "message": f"data.js 生成失败：{exc}"}
        return

    data_js = _extract_js(data_js_text)
    if not data_js.strip():
        yield {"type": "error", "message": "data.js 生成为空，请重试"}
        return

    logger.info("data.js 生成完毕：%d 字符", len(data_js))

    data_js_signatures = _extract_function_signatures(data_js)
    logger.info("data.js 接口契约：\n%s", data_js_signatures)
    yield {"type": "progress", "message": f"[1/3] data.js 完成（{len(data_js)} 字符）"}

    # ── Step 2: 生成 effects.js ─────────────────────────────────────
    yield {"type": "progress", "message": f"[2/3] 正在生成效果注册表 (effects.js)，模型: {code_model}..."}

    effects_messages = [
        {"role": "system", "content": _EFFECTS_SYSTEM_PROMPT},
        {"role": "user",   "content": _EFFECTS_USER_TEMPLATE.format(
            summary            = summary,
            sec_gameplay       = sec_gameplay[:8000]  or "（暂无）",
            data_js            = data_js[:12000],
            data_js_signatures = data_js_signatures,
        )},
    ]

    effects_js_text = ""
    effects_token_count = 0
    try:
        async for _, content in _stream_llm(llm, effects_messages):
            effects_js_text += content
            effects_token_count += len(content)
            yield {"type": "token", "text": content}
            if effects_token_count % 300 < len(content):
                yield {"type": "progress", "message": f"[2/3] effects.js 生成中... {effects_token_count} 字符"}
    except Exception as exc:
        logger.exception("effects.js 生成失败：%s", exc)
        yield {"type": "error", "message": f"effects.js 生成失败：{exc}"}
        return

    effects_js = _extract_js(effects_js_text)
    if not effects_js.strip():
        yield {"type": "error", "message": "effects.js 生成为空，请重试"}
        return

    logger.info("effects.js 生成完毕：%d 字符", len(effects_js))
    yield {"type": "progress", "message": f"[2/3] effects.js 完成（{len(effects_js)} 字符）"}

    # ── Step 3: 生成 scenes.js ──────────────────────────────────────
    yield {"type": "progress", "message": f"[3/3] 正在生成场景层 (scenes.js)，模型: {code_model}..."}

    scenes_messages = [
        {"role": "system", "content": _SCENES_SYSTEM_PROMPT},
        {"role": "user",   "content": _SCENES_USER_TEMPLATE.format(
            summary            = summary,
            sec_gameplay       = sec_gameplay[:6000]  or "（暂无）",
            sec_worldview      = sec_worldview[:2000] or "（暂无）",
            art_manifest       = art_manifest,
            data_js            = data_js[:10000],
            data_js_signatures = data_js_signatures,
            effects_js         = effects_js[:10000],
        )},
    ]

    scenes_js_text = ""
    scenes_token_count = 0
    try:
        async for _, content in _stream_llm(llm, scenes_messages):
            scenes_js_text += content
            scenes_token_count += len(content)
            yield {"type": "token", "text": content}
            if scenes_token_count % 300 < len(content):
                yield {"type": "progress", "message": f"[3/3] scenes.js 生成中... {scenes_token_count} 字符"}
    except Exception as exc:
        logger.exception("scenes.js 生成失败：%s", exc)
        yield {"type": "error", "message": f"scenes.js 生成失败：{exc}"}
        return

    scenes_js = _extract_js(scenes_js_text)
    if not scenes_js.strip():
        yield {"type": "error", "message": "scenes.js 生成为空，请重试"}
        return

    logger.info("scenes.js 初次生成：%d 字符", len(scenes_js))

    # ── Step 3.5: 截断检测 + 自动续写 ──────────────────────────────
    MAX_CONTINUATIONS = 2
    for cont_round in range(MAX_CONTINUATIONS):
        is_complete, missing_info = _is_scenes_js_complete(scenes_js)
        if is_complete:
            logger.info("scenes.js 完整性校验通过")
            break

        logger.warning("scenes.js 截断检测（第 %d 轮）：%s", cont_round + 1, missing_info)
        yield {
            "type": "progress",
            "message": f"⚠ scenes.js 不完整（{missing_info}），自动续写第 {cont_round + 1} 轮...",
        }

        tail_lines = scenes_js.strip().splitlines()[-150:]
        tail_code = "\n".join(tail_lines)

        cont_messages = [
            {"role": "system", "content": _SCENES_CONTINUE_SYSTEM},
            {"role": "user",   "content": _SCENES_CONTINUE_USER.format(
                tail_code=tail_code,
                missing_info=missing_info,
            )},
        ]

        cont_text = ""
        cont_chars = 0
        try:
            async for _, content in _stream_llm(llm, cont_messages):
                cont_text += content
                cont_chars += len(content)
                yield {"type": "token", "text": content}
                if cont_chars % 300 < len(content):
                    yield {"type": "progress", "message": f"[续写 {cont_round + 1}] {cont_chars} 字符..."}
        except Exception as exc:
            logger.exception("scenes.js 续写失败：%s", exc)
            yield {"type": "progress", "message": f"⚠ 续写失败（{exc}），使用已有代码继续"}
            break

        cont_js = _extract_js(cont_text)
        if cont_js.strip():
            scenes_js = scenes_js.rstrip() + "\n\n" + cont_js.strip()
            logger.info("scenes.js 续写后：%d 字符（+%d）", len(scenes_js), len(cont_js))
            yield {"type": "progress", "message": f"[续写 {cont_round + 1}] 拼接完成（+{len(cont_js)} 字符，总 {len(scenes_js)} 字符）"}
        else:
            logger.warning("续写输出为空，跳过")
            break
    else:
        final_complete, final_missing = _is_scenes_js_complete(scenes_js)
        if not final_complete:
            logger.warning("scenes.js 经过 %d 轮续写仍不完整：%s", MAX_CONTINUATIONS, final_missing)
            yield {"type": "progress", "message": f"⚠ scenes.js 经过 {MAX_CONTINUATIONS} 轮续写仍不完整（{final_missing}），将由 reviewer 补全"}

    logger.info("scenes.js 最终长度：%d 字符", len(scenes_js))

    # ── 跨文件接口校验 ─────────────────────────────────────────────
    api_warnings = _validate_cross_file_calls(data_js, effects_js, scenes_js)
    if api_warnings:
        for w in api_warnings:
            logger.warning("跨文件接口不匹配：%s", w)
        warn_text = "；".join(api_warnings[:5])
        yield {"type": "progress", "message": f"⚠ 接口校验发现 {len(api_warnings)} 处参数不匹配：{warn_text}"}
    else:
        logger.info("跨文件接口校验通过")

    # ── Step 4: 模板组装 ────────────────────────────────────────────
    sr = state.get("structured_req") or {}
    game_title = sr.get("title") or sr.get("theme") or "Roguelike Game"

    index_html = _INDEX_HTML_TEMPLATE.format(game_title=game_title)
    style_css  = _STYLE_CSS
    main_js    = _MAIN_JS_TEMPLATE.format()

    assembled_html = assemble_full_html(game_title, data_js, effects_js, scenes_js, main_js)

    files = {
        "index.html":  index_html,
        "style.css":   style_css,
        "data.js":     data_js,
        "effects.js":  effects_js,
        "scenes.js":   scenes_js,
        "main.js":     main_js,
    }

    total_js = len(data_js) + len(effects_js) + len(scenes_js) + len(main_js)
    yield {"type": "progress", "message": f"代码生成完毕（data: {len(data_js)} + effects: {len(effects_js)} + scenes: {len(scenes_js)} = {total_js} 字符）"}
    yield {
        "type": "done",
        "game_code": assembled_html,
        "files": files,
    }

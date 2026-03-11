"""
H5 游戏代码生成 Agent
基于已确认的 GDD + 美术资源清单，生成可直接在浏览器运行的 Phaser.js 3 单关卡卡牌战斗原型。
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
# System Prompt
# ──────────────────────────────────────────────────────────────────────────────

_SYSTEM_PROMPT = """你是资深 H5 游戏工程师，使用 Phaser 3 输出一个 **Roguelike 卡牌原型**。

## 铁律（违反任何一条 = 不合格）
1. **只输出纯 HTML**：从 `<!DOCTYPE html>` 到 `</html>` 结束，不加说明文字、markdown 标记
2. **相对路径**：所有图片 URL 以 `/static/` 开头，禁止 `http://localhost` 等绝对地址
3. **背景消除**：角色/对手 PNG 必须在 BootScene.create() 中调用 `removeBackground(this, key)` 抠图；**卡牌完整图和背景图不处理**
4. **卡牌完整图优先**：每张卡牌直接以 `card_{id}` 完整图（320×480，含边框+插画+文字）展示，`setDisplaySize(145, 217)`；图片不存在才降级为程序化卡框
5. **分辨率**：1280×720，渲染器 `type: Phaser.AUTO`
6. **Phaser 版本**：`https://cdn.jsdelivr.net/npm/phaser@3.88.2/dist/phaser.min.js`

---

## Roguelike 框架设计原则

**核心循环**：玩家出牌/使用能力 → 效果生效 → 结束回合 → 对手行动 → 循环直到胜/负。单局单场景，胜负后一键重玩。

**效果实现规则**：
- 卡牌效果由玩法文档定义，你需要读懂效果描述并将其翻译为 JavaScript 逻辑
- CARDS 数组中每张卡的字段按效果自由设计（可有 `value`, `times`, `duration`, `extra` 等任意字段）
- `playCard` 函数须逐一判断 `card.effect` 并执行对应逻辑，不要遗漏任何效果
- 对于控制/增益类效果（跳过回合、额外摸牌、持续效果等），使用状态标志或计时器实现
- 对于特殊异变类（改变游戏规则的效果），大胆实现，但保持可玩性

---

## 必须实现的全局工具函数（写在所有 Scene 类之前）

### 1. 程序化形象纹理（图片失败时兜底）
```js
function makeFallbackTexture(scene, key, color, w, h) {
  if (scene.textures.exists(key) && scene.textures.get(key).source[0].width > 4) return;
  const g = scene.make.graphics({ add: false });
  g.fillStyle(color, 1).fillRoundedRect(0, 0, w, h, 14);
  g.lineStyle(3, 0xffffff, 0.45).strokeRoundedRect(3, 3, w-6, h-6, 12);
  const lc = Phaser.Display.Color.IntegerToColor(color).lighten(35).color;
  g.fillStyle(lc, 1).fillCircle(w/2, h*0.28, w*0.2);
  g.generateTexture(key, w, h);
  g.destroy();
}
```

### 2. 状态条（HP/能量/护盾等）
```js
function makeHPBar(scene, x, y, w, h, maxHp, fillColor) {
  scene.add.graphics().fillStyle(0x111111, 0.85).fillRect(x, y, w, h).setDepth(10);
  const bar = scene.add.graphics().setDepth(11);
  const txt = scene.add.text(x+w/2, y+h/2, '', {fontSize:'11px', color:'#fff'}).setOrigin(0.5).setDepth(12);
  const refresh = (cur, max) => {
    bar.clear();
    const r = Math.max(0, cur/max);
    bar.fillStyle(r>0.5 ? fillColor : r>0.25 ? 0xffaa00 : 0xff3333, 1).fillRect(x, y, w*r, h);
    txt.setText(`${Math.ceil(cur)}/${max}`);
  };
  refresh(maxHp, maxHp);
  return { refresh };
}
```

### 3. 卡牌精灵（完整卡牌图直接展示，fallback 为程序化卡框）
```js
function makeCard(scene, x, y, card) {
  // 卡牌图尺寸：320×480 → 游戏内按 145×217 显示（更大尺寸减少缩放模糊）
  const W=145, H=217;
  const c = scene.add.container(x, y).setDepth(8).setSize(W, H).setInteractive({useHandCursor:true});

  const imgKey = `card_${card.id}`;
  const hasImg = scene.textures.exists(imgKey) && scene.textures.get(imgKey).source[0].width > 4;

  if (hasImg) {
    // 完整卡牌图（含边框+插画+文字），直接缩放展示，不做任何处理
    const img = scene.add.image(0, 0, imgKey).setDisplaySize(W, H);
    // 高亮描边（hover 时显示）
    const hl = scene.add.graphics().lineStyle(3, 0xffd700, 0).strokeRoundedRect(-W/2,-H/2,W,H,6);
    const costDot = scene.add.graphics().fillStyle(0x000000,0.78).fillCircle(-W/2+15,-H/2+15,14);
    const costTxt = scene.add.text(-W/2+15,-H/2+15,`${card.cost}`,{fontSize:'15px',color:'#fff',fontStyle:'bold'}).setOrigin(0.5);
    c.add([img, costDot, costTxt, hl]);
    c.setData('hl', hl);
  } else {
    // fallback：程序化卡框 + 费用 + 卡名 + 效果 emoji
    const bg = scene.add.graphics();
    bg.fillStyle(0x0d0d22, 0.96).fillRoundedRect(-W/2,-H/2,W,H,8);
    bg.lineStyle(2, card.color, 0.9).strokeRoundedRect(-W/2,-H/2,W,H,8);
    const cg = scene.add.graphics().fillStyle(card.color,1).fillCircle(-W/2+13,-H/2+13,12);
    const ct = scene.add.text(-W/2+13,-H/2+13,`${card.cost}`,{fontSize:'13px',color:'#fff',fontStyle:'bold'}).setOrigin(0.5);
    const nt = scene.add.text(0,-H/2+28,card.name,{fontSize:'11px',color:'#fff',fontStyle:'bold',wordWrap:{width:W-12},align:'center'}).setOrigin(0.5);
    const typeEmoji = {attack:'⚔',defend:'🛡',buff:'✨',control:'❄',special:'🌀'}[card.type]||'✦';
    const ic = scene.add.text(0,-H/2+86,typeEmoji,{fontSize:'36px'}).setOrigin(0.5);
    const sep = scene.add.graphics().lineStyle(1,card.color,0.35).lineBetween(-W/2+6,H/2-46,W/2-6,H/2-46);
    const dt = scene.add.text(0,H/2-26,card.desc,{fontSize:'9px',color:'#ccc',wordWrap:{width:W-10},align:'center'}).setOrigin(0.5);
    c.add([bg,cg,ct,nt,ic,sep,dt]);
  }

  return c;
}
```

### 4. 飘字动画
```js
function floatText(scene, x, y, msg, color) {
  const t = scene.add.text(x, y, msg, {fontSize:'28px',color:color||'#ff4444',fontStyle:'bold',stroke:'#000',strokeThickness:5}).setOrigin(0.5).setDepth(22);
  scene.tweens.add({targets:t, y:y-80, alpha:{from:1,to:0}, duration:900, onComplete:()=>t.destroy()});
}
```

### 5. 角色背景消除（必须调用，替代 MULTIPLY）
AI 生成的角色/敌人 PNG 可能带白色底或棋盘格灰底。
调用此函数可采样四角识别背景色，将其透明化，使精灵无缝融入深色场景。
```js
function removeBackground(scene, key, tolerance) {
  tolerance = tolerance || 55;
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
        Math.abs(rgb[0]-b[0]) < 35 && Math.abs(rgb[1]-b[1]) < 35 && Math.abs(rgb[2]-b[2]) < 35
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
```

---

## 三个 Scene（必须完整实现）

### BootScene
```js
class BootScene extends Phaser.Scene {
  constructor(){super('Boot')}
  preload(){
    // ★ 逐行加载所有美术资源（相对路径）：
    //   背景图：this.load.image('bg_main', '/static/art/SESSION_ID/bg_main_scene.jpg');
    //   主角：  this.load.image(PLAYER_IMG, '/static/art/SESSION_ID/char_protagonist.png');
    //   对手：  对每个对手一行，key = 对手的 img 字段
    //   卡牌图标（每张卡牌一行，key = 'card_{card.id}'）：
    //           this.load.image('card_xxx', '/static/art/SESSION_ID/card_xxx.png');
    //   其他资源：按美术清单逐行添加
    const bar=this.add.graphics();
    this.load.on('progress',v=>{bar.clear().fillStyle(THEME_COLOR,1).fillRect(240,354,800*v,12);});
  }
  create(){
    makeFallbackTexture(this, PLAYER_IMG, 0x3366cc, 160, 160);
    OPPONENTS.forEach(e=>makeFallbackTexture(this, e.img, e.color, 160, 160));
    // ★ 背景消除：对所有角色/敌人图调用 removeBackground（消除白底或棋盘格灰底）
    removeBackground(this, PLAYER_IMG);
    OPPONENTS.forEach(e => removeBackground(this, e.img));
    // ★ 卡牌纹理切换为 NEAREST 采样，消除双线性滤波糊化，保持图像锐利
    CARDS.forEach(card => {
      const key = `card_${card.id}`;
      if (this.textures.exists(key) && this.textures.get(key).source[0].width > 4) {
        this.textures.get(key).setFilter(Phaser.Textures.FilterMode.NEAREST);
      }
    });
    // 背景兜底（渐变深色）
    if(!this.textures.exists('bg_main')||this.textures.get('bg_main').source[0].width<=4){
      const g=this.make.graphics({add:false});
      g.fillGradientStyle(0x0a0a2a,0x0a0a2a,0x1a0a3a,0x1a0a3a,1);
      g.fillRect(0,0,1280,720); g.generateTexture('bg_main',1280,720); g.destroy();
    }
    this.scene.start('Menu');
  }
}
```

### MenuScene
```js
class MenuScene extends Phaser.Scene {
  constructor(){super('Menu')}
  create(){
    const hasBg=this.textures.exists('bg_menu')&&this.textures.get('bg_menu').source[0].width>4;
    this.add.image(640,360,hasBg?'bg_menu':'bg_main').setDisplaySize(1280,720).setDepth(0);
    const ov=this.add.graphics().setDepth(1);
    ov.fillGradientStyle(0,0,0,0,0.55,0.55,0,0).fillRect(0,0,1280,400);
    ov.fillGradientStyle(0,0,0,0,0,0,0.7,0.7).fillRect(0,400,1280,320);

    this.add.text(640,200,GAME_TITLE,{fontSize:'62px',color:'#ffd700',stroke:'#000',strokeThickness:9,fontStyle:'bold'}).setOrigin(0.5).setDepth(5);
    this.add.text(640,280,'ROGUELIKE',{fontSize:'16px',color:'#aaaaff',letterSpacing:10}).setOrigin(0.5).setDepth(5);

    const hexColor='#'+THEME_COLOR.toString(16).padStart(6,'0');
    const btn=this.add.text(640,420,'  开始游戏  ',{fontSize:'34px',backgroundColor:hexColor,padding:{x:30,y:14},color:'#fff'})
      .setOrigin(0.5).setInteractive({useHandCursor:true}).setDepth(5);
    btn.on('pointerover',()=>btn.setAlpha(0.8));
    btn.on('pointerout',()=>btn.setAlpha(1));
    btn.on('pointerdown',()=>this.scene.start('Battle'));
  }
}
```

### BattleScene（核心，完整实现）
```js
class BattleScene extends Phaser.Scene {
  constructor(){super('Battle')}

  create(){
    // ── 状态初始化（按游戏类型可扩展字段）──
    this.pl = {hp:PLAYER_HP, maxHp:PLAYER_HP, shield:0, energy:MAX_ENERGY, maxEnergy:MAX_ENERGY};
    // 从 OPPONENTS 随机选一个
    const oi = Phaser.Math.Between(0, OPPONENTS.length-1);
    this.en = {...OPPONENTS[oi], hp:OPPONENTS[oi].hp, shield:0};
    this.deck = Phaser.Utils.Array.Shuffle([...STARTER_DECK]);
    this.hand=[]; this.discard=[]; this.cards=[]; this.busy=false;
    // ★ 在此添加游戏类型特有的状态字段（如 stun 标志、buff 计数器等）

    // ── 背景与遮罩 ──
    const hasBg=this.textures.exists('bg_main')&&this.textures.get('bg_main').source[0].width>4;
    this.add.image(640,360,hasBg?'bg_main':'bg_main').setDisplaySize(1280,720).setDepth(0);
    this.add.graphics().fillStyle(0x000000,0.55).fillRect(0,530,1280,190).setDepth(2);

    // ── 主角 Sprite（背景已在 BootScene.create 中消除）──
    const pReal=this.textures.exists(PLAYER_IMG)&&this.textures.get(PLAYER_IMG).source[0].width>4;
    this.pSpr=this.add.image(210,330,pReal?PLAYER_IMG:'player_fallback')
      .setDisplaySize(160,160).setDepth(4);

    // ── 主角 HUD ──
    this.pHPBar=makeHPBar(this,20,475,220,18,PLAYER_HP,0x2299ff);
    this.add.text(20,456,'HP',{fontSize:'12px',color:'#aaa'}).setDepth(10);
    this.shTxt=this.add.text(20,496,'护盾: 0',{fontSize:'13px',color:'#88ccff'}).setDepth(10);
    this.enTxt=this.add.text(20,516,'',{fontSize:'15px',color:'#ffdd44',fontStyle:'bold'}).setDepth(10);

    // ── 对手 Sprite（背景已在 BootScene.create 中消除）──
    const eReal=this.textures.exists(this.en.img)&&this.textures.get(this.en.img).source[0].width>4;
    this.eSpr=this.add.image(1000,300,eReal?this.en.img:'enemy_fallback')
      .setDisplaySize(160,160).setDepth(4);
    if(!eReal) this.eSpr.setTint(this.en.color);

    // ── 对手 HUD ──
    this.eHPBar=makeHPBar(this,870,140,210,18,this.en.hp,0x22bb44);
    this.add.text(870,120,this.en.name,{fontSize:'15px',color:'#ffdd44',fontStyle:'bold'}).setDepth(10);
    this.intTxt=this.add.text(870,162,'',{fontSize:'12px',color:'#ffaaaa'}).setDepth(10);

    // ── 结束回合 ──
    const eb=this.add.text(1155,660,'结束回合',{fontSize:'18px',backgroundColor:'#332211',padding:{x:14,y:8},color:'#ffdd88'})
      .setOrigin(0.5).setInteractive({useHandCursor:true}).setDepth(10);
    eb.on('pointerover',()=>eb.setAlpha(0.75));
    eb.on('pointerout',()=>eb.setAlpha(1));
    eb.on('pointerdown',()=>{if(!this.busy)this.endTurn();});

    this.startTurn();
  }

  startTurn(){
    this.pl.energy=this.pl.maxEnergy;
    this.pl.shield=0;
    // ★ 回合开始时处理持续效果（如已有 stun 则不减）
    for(let i=0;i<5-this.hand.length;i++){
      if(!this.deck.length){this.deck=Phaser.Utils.Array.Shuffle(this.discard.splice(0));}
      if(this.deck.length) this.hand.push(this.deck.pop());
    }
    this.renderHand(); this.updateHUD();
    // 显示对手意图（按对手数据）
    this.intTxt.setText(`意图：攻击 ${this.en.atk}`);
  }

  renderHand(){
    this.cards.forEach(c=>c.destroy()); this.cards=[];
    const n=this.hand.length, gap=120, sx=640-(n-1)*gap/2;
    this.hand.forEach((cid,i)=>{
      const card=CARDS.find(c=>c.id===cid)||CARDS[0];
      const x=sx+i*gap, y=636;
      const obj=makeCard(this,x,y,card);
      obj.on('pointerover',()=>{
        obj.y=y-32; obj.setDepth(15);
        // 有高亮层（完整卡图模式）时显示金色描边
        const hl=obj.getData('hl');
        if(hl) hl.setAlpha(1);
      });
      obj.on('pointerout',()=>{
        obj.y=y; obj.setDepth(8);
        const hl=obj.getData('hl');
        if(hl) hl.setAlpha(0);
      });
      obj.on('pointerdown',()=>{if(!this.busy)this.playCard(i);});
      this.cards.push(obj);
    });
  }

  playCard(idx){
    const cid=this.hand[idx], card=CARDS.find(c=>c.id===cid)||CARDS[0];
    if(this.pl.energy<card.cost){floatText(this,640,400,'能量不足！','#ffaa00');return;}
    this.pl.energy-=card.cost;
    this.hand.splice(idx,1); this.discard.push(cid);

    // ★★ 根据玩法文档的卡牌效果逐一实现，每种 effect 一个 if/else 分支
    // 以下是通用基础效果模板，必须按实际卡牌效果扩展/替换：
    if(card.effect==='damage'){
      let d=card.value;
      if(this.en.shield>0){const a=Math.min(this.en.shield,d);this.en.shield-=a;d-=a;}
      this.en.hp=Math.max(0,this.en.hp-d);
      floatText(this,1000,260,`-${d}`,'#ff4444');
      this.tweens.add({targets:this.eSpr,x:1020,duration:55,yoyo:true,repeat:3});
    } else if(card.effect==='damage2'){
      // 两次伤害
      let total=0;
      for(let t=0;t<2;t++){
        let d=card.value;
        if(this.en.shield>0){const a=Math.min(this.en.shield,d);this.en.shield-=a;d-=a;}
        this.en.hp=Math.max(0,this.en.hp-d); total+=d;
      }
      floatText(this,1000,260,`-${total}`,'#ff4444');
      this.tweens.add({targets:this.eSpr,x:1020,duration:55,yoyo:true,repeat:5});
    } else if(card.effect==='shield'){
      this.pl.shield+=card.value; floatText(this,210,280,`+${card.value}护盾`,'#88ccff');
    } else if(card.effect==='heal'){
      this.pl.hp=Math.min(this.pl.maxHp,this.pl.hp+card.value);
      floatText(this,210,280,`+${card.value}HP`,'#44ff88');
    } else if(card.effect==='draw'){
      for(let d=0;d<card.value;d++){
        if(!this.deck.length)this.deck=Phaser.Utils.Array.Shuffle(this.discard.splice(0));
        if(this.deck.length)this.hand.push(this.deck.pop());
      }
      floatText(this,640,400,`摸${card.value}张`,'#aaddff');
    } else if(card.effect==='weaken'){
      this.en._weakened=(this.en._weakened||0)+card.value;
      floatText(this,1000,260,`弱化-${card.value}`,'#ff8833');
    } else if(card.effect==='stun'){
      // 跳过对手下一回合行动
      this.en._stunned=true;
      floatText(this,1000,260,'眩晕！','#cc44ff');
    } else if(card.effect==='energy'){
      // 恢复能量
      this.pl.energy=Math.min(this.pl.maxEnergy,this.pl.energy+card.value);
      floatText(this,640,400,`+${card.value}能量`,'#ffdd44');
    }
    // ★ 继续按玩法文档添加其他 effect 分支...

    this.updateHUD(); this.renderHand();
    if(this.en.hp<=0){this.onWin();return;}
  }

  endTurn(){
    this.busy=true;
    this.discard.push(...this.hand); this.hand=[];
    this.renderHand();
    this.time.delayedCall(500,()=>{
      // ★ 检查眩晕等控制效果
      if(this.en._stunned){
        this.en._stunned=false;
        floatText(this,1000,260,'被眩晕，跳过回合','#cc44ff');
        this.time.delayedCall(700,()=>{this.busy=false;this.startTurn();});
        return;
      }
      let dmg=Math.max(0, this.en.atk-(this.en._weakened||0));
      this.en._weakened=0;
      const abs=Math.min(this.pl.shield,dmg); this.pl.shield-=abs; dmg-=abs;
      this.pl.hp=Math.max(0,this.pl.hp-dmg);
      if(dmg>0){
        floatText(this,210,260,`-${dmg}`,'#ff6644');
        this.tweens.add({targets:this.pSpr,x:190,duration:55,yoyo:true,repeat:3});
      }
      this.updateHUD();
      if(this.pl.hp<=0){this.onLose();return;}
      this.time.delayedCall(500,()=>{this.busy=false;this.startTurn();});
    });
  }

  updateHUD(){
    this.pHPBar.refresh(this.pl.hp,this.pl.maxHp);
    this.eHPBar.refresh(this.en.hp,this.en.maxHp);
    this.shTxt.setText(`护盾: ${this.pl.shield}`);
    this.enTxt.setText(`能量: ${this.pl.energy}/${this.pl.maxEnergy}`);
  }

  onWin(){
    this.busy=true;
    this.add.rectangle(640,360,1280,720,0x000000,0.78).setDepth(20);
    this.add.text(640,250,'胜利！',{fontSize:'80px',color:'#ffd700',fontStyle:'bold',stroke:'#000',strokeThickness:10}).setOrigin(0.5).setDepth(25);
    this.add.text(640,360,`击败了 ${this.en.name}`,{fontSize:'26px',color:'#aaffaa'}).setOrigin(0.5).setDepth(25);
    this.add.text(640,490,'点击任意处重玩',{fontSize:'20px',color:'#aaa'}).setOrigin(0.5).setDepth(25);
    this.input.once('pointerdown',()=>this.scene.restart());
  }

  onLose(){
    this.busy=true;
    this.add.rectangle(640,360,1280,720,0x000000,0.82).setDepth(20);
    this.add.text(640,250,'你倒下了...',{fontSize:'72px',color:'#ff4444',fontStyle:'bold',stroke:'#000',strokeThickness:8}).setOrigin(0.5).setDepth(25);
    this.add.text(640,360,'再战一局？',{fontSize:'24px',color:'#aaa'}).setOrigin(0.5).setDepth(25);
    this.add.text(640,490,'点击任意处重新开始',{fontSize:'20px',color:'#888'}).setOrigin(0.5).setDepth(25);
    this.input.once('pointerdown',()=>this.scene.restart());
  }
}
```

### 游戏入口
```js
new Phaser.Game({
  type: Phaser.WEBGL,
  width:1280, height:720,
  backgroundColor:'#0a0a1a',
  scene:[BootScene, MenuScene, BattleScene],
  powerPreference:'high-performance',
});
```

---

## 关键注意
- `playCard` 的 effect 分支必须覆盖玩法文档中所有 10 张卡的效果，不得遗漏
- 控制/增益/异变类效果（眩晕、能量增加、摸牌、改变规则等）一律实现，不要省略
- 背景消除：BootScene.create() 中必须对 PLAYER_IMG 和每个 OPPONENTS[i].img 调用 `removeBackground(this, key)`，BattleScene 中的精灵**不加** blendMode
- `busy` 标志防止对手回合出牌
- 牌库耗尽自动将弃牌堆洗入（`Phaser.Utils.Array.Shuffle`）
- 图片校验：`textures.get(key).source[0].width > 4`"""

# ──────────────────────────────────────────────────────────────────────────────
# User Prompt 模板
# ──────────────────────────────────────────────────────────────────────────────

_USER_TEMPLATE = """根据以下 GDD 生成完整的 Roguelike 卡牌原型 HTML 文件。

## 游戏概要
{summary}

## 玩法设计（核心参考：读取 10 张卡牌的名称/效果/数值，对手设计）
{sec_gameplay}

## 世界观（主角/对手命名风格、主题色调、视觉气质）
{sec_worldview}

## 已生成美术资源（BootScene.preload() 中全部加载，相对路径）
格式：key → URL
{art_manifest}

## 实现要求

### 数据层（`<script>` 最顶部定义常量）
```js
const GAME_TITLE  = "...";             // 从 GDD 取游戏名
const THEME_COLOR = 0x6633cc;          // 世界观主色（整数十六进制）
const PLAYER_HP   = 80;               // 主角初始HP
const MAX_ENERGY  = 3;                // 每回合能量上限
const PLAYER_IMG  = 'char_protagonist';

// 卡牌池：严格按照玩法文档的 10 张卡牌定义
// effect 字段命名自由（damage/shield/heal/draw/weaken/stun/energy/...）
// 按实际效果自由添加 value/times/duration/extra 等所需字段
const CARDS = [
  {{ id:'card_id', name:'卡牌名', effect:'xxx', value:N, desc:'效果描述', color:0xRRGGBB }},
  // ... 共 10 张，一一对应玩法文档，不需要 type 和 cost 字段
];

// 初始牌组（卡牌 id 数组，可重复，建议 10 张）
const STARTER_DECK = [...];

// 对手池：从玩法文档提取 2-3 个挑战/对手
// img 必须与美术资源 key 匹配
const OPPONENTS = [
  {{ name:'...', hp:N, atk:N, shield:0, color:0xRRGGBB, img:'char_enemy_xxx' }},
  // ...
];
```

### 加载规则（BootScene.preload 中每张图写一行）
- 背景图：key 与美术资源 key 一致（如 'bg_main', 'bg_menu'）
- 主角图：key = PLAYER_IMG 的值
- 对手图：key = OPPONENTS[i].img 的值
- **完整卡牌图**：每张卡牌一行，key 格式固定为 `'card_' + card.id`（卡牌图尺寸 320×480，已包含边框+插画+文字）
  ```js
  this.load.image('card_xxx', '/static/art/SESSION_ID/card_xxx.png');
  ```
- 所有路径以 `/static/` 开头

### 渲染规则
- **角色/对手图**：在 BootScene.create() 中调用 `removeBackground(this, key)` 消除白底/棋盘格灰底；BattleScene 中直接 `add.image(...).setDisplaySize(160, 160)` 即可，**不加任何 blendMode**
- **卡牌完整图**（有自己的背景色）：直接 `setDisplaySize(145, 217)` 展示，**不调用 removeBackground**
- **背景图**：直接展示，不做处理
- 图片加载校验：`textures.get(key).source[0].width > 4`

### 效果实现规则（最重要）
- `playCard` 函数须按玩法文档为每张卡的 effect 写专属实现
- 通用基础效果（damage/shield/heal/draw/weaken）已在模板提供
- **其他主题化效果必须完整实现**：跳过对手回合（stun）、恢复能量、改变最大能量、造成多段伤害、永久增益、改变摸牌数等
- 控制类效果（stun/freeze）：设置 `this.en._stunned=true`，endTurn 中检查跳过
- 持续增益：在 `startTurn` 开头处理计数器减少
- 特殊/异变类：大胆实现，用飘字提示效果（floatText）
"""


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
    """
    构建美术资源清单，供 LLM 在 preload() 中加载。
    格式：  key → /static/art/{sid}/{filename}.ext
    """
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


def _extract_html(text: str) -> str:
    """从 LLM 输出中提取 HTML（兼容带 markdown 代码块的情况）。"""
    pattern = r"```(?:html)?\s*([\s\S]+?)```"
    m = re.search(pattern, text)
    if m:
        return m.group(1).strip()
    return text.strip()


# ──────────────────────────────────────────────────────────────────────────────
# 主函数（SSE 流式调用）
# ──────────────────────────────────────────────────────────────────────────────

async def generate_game_code_stream(
    state: GameDesignState,
) -> AsyncGenerator[dict, None]:
    """
    流式生成 H5 游戏代码，yield 进度事件。
    事件格式：
      {"type": "token",    "text": "..."}
      {"type": "progress", "message": "..."}
      {"type": "done",     "game_code": "<!DOCTYPE html>..."}
      {"type": "error",    "message": "..."}
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

    yield {"type": "progress", "message": "正在分析设计文档，规划游戏架构..."}

    llm = ChatOpenAI(
        model=settings.CODE_MODEL,
        api_key=settings.OPENAI_API_KEY,
        base_url=settings.OPENAI_BASE_URL,
        streaming=True,
        temperature=0.2,
    )

    messages = [
        {"role": "system", "content": _SYSTEM_PROMPT},
        {"role": "user",   "content": _USER_TEMPLATE.format(
            summary       = summary,
            sec_gameplay  = sec_gameplay[:5000]  or "（暂无）",
            sec_worldview = sec_worldview[:2000] or "（暂无）",
            art_manifest  = art_manifest,
        )},
    ]

    yield {"type": "progress", "message": "LLM 开始生成 Phaser.js 代码..."}

    full_text = ""
    async for chunk in llm.astream(messages):
        raw = chunk.content
        # 部分模型（如 gpt-5.3-codex）返回内容块列表而非纯字符串
        if isinstance(raw, list):
            token = "".join(
                part.get("text", "") if isinstance(part, dict) else str(part)
                for part in raw
            )
        else:
            token = raw or ""
        if token:
            full_text += token
            yield {"type": "token", "text": token}

    game_code = _extract_html(full_text)

    yield {"type": "progress", "message": "代码生成完毕，正在处理..."}
    yield {"type": "done", "game_code": game_code}

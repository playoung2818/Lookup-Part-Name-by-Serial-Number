/* Footprints traced in the reference image's 2000 × 888 display coordinates.
   Heights and colors are illustrative, not surveyed dimensions. No dependencies. */
(() => {
  'use strict';
  if (new URLSearchParams(window.location.search).get('embed') === '1') {
    document.body.classList.add('embedded');
  }
  const colors = {
    storage: ['Storage & accessories', '#91aec9'],
    outgoing: ['Outgoing', '#70b4aa'],
    work: ['Working & packing', '#e5bd76'],
    production: ['Production', '#899fc3'],
    receiving: ['Incoming receiving', '#87ba91'],
    special: ['RMA & hold', '#cb969a']
  };
  const fixtures = [];
  function add(name, x, y, w, d, category, height = 42, description = '', angle = 0) {
    fixtures.push({name, x, y, w, d, category, height, description, angle});
  }
  add('WH10Part · 5', 15, 18, 104, 48, 'storage', 65, 'Parts storage.');
  add('WH015 · 6', 133, 18, 117, 51, 'storage', 65, 'PCIe card / MezIO / M.2 kit.');
  [[82,78,4,'Accessories / trays / cables / wall mount kits / dampers / DIN rail.'],[181,78,3,'Accessories / fans / dust covers / terminal blocks.'],[276,83,2,'Power adapters and power cables.']].forEach(([y,d,n,desc]) => add(`WH01S · ${n}`,16,y,39,d,'storage',65,desc));
  [[78,34,7,'PCIe card.'],[133,67,8,'OS storage.'],[217,100,9,'POC / power backup.']].forEach(([y,d,n,desc]) => add(`WH01S · ${n}`,200,y,46,d,'storage',65,desc));
  add('WH01S · 1',64,362,151,33,'storage',58,'NRU series / semi cable / Nuvo-2500.');
  add('WH01S · 2',286,14,186,67,'storage',68,'Nuvo-9000 / Nuvo-10000 series.');
  add('WH01S · 3',480,16,175,66,'storage',68,'Nuvo-9000 / Nuvo-10000 series.');
  add('WH11 / WH12 / WH99 / WH01S · 4',661,17,140,65,'storage',68,'Nuvo-11000 series.');
  add('WH601 · 5',807,16,61,65,'storage',65);
  add('Hold',876,17,71,48,'special',35,'Hold area.');
  add('WH01S · 1',287,95,80,187,'storage',68,'Nuvo-8000 / Nuvo-7000 series.');
  [[114,68,1],[218,66,2],[318,64,3],[424,58,4]].forEach(([y,d,n]) => add(`WH01X · ${n}`,495,y,78,d,'outgoing',46,'Outgoing staging.'));
  [[109,159,1],[274,147,2],[424,104,3]].forEach(([y,d,n]) => add(`WH01S · ${n}`,583,y,72,d,'outgoing',46,'Outgoing staging.'));
  add('WH01X · 4',181,445,151,39,'outgoing',38,'Outgoing staging; angled footprint.',48);
  add('Pending inspection',771,144,68,314,'work',28,'Pending inspection / 待驗暫存區.');
  [148,275,410,542].forEach((y,i) => add(`Working area ${i+1}`,854,y,142,i===3?121:126,'work',29,'Central working area.'));
  add('Scale',787,490,50,36,'work',22,'Weighing station.');
  add('Packing bench',777,533,62,136,'work',29);
  add('Packing bench',848,674,136,30,'work',29);
  add('Production cart',1034,173,60,208,'production',32);
  add('Production cart',1036,433,58,194,'production',32);
  [145,294,439,583].forEach((y,i) => add(`Production bench ${i+1}`,1290,y,524,77,'production',29,'Production workbench.'));
  add('Customer toolkit / incoming RMA',1123,19,184,60,'special',35,'Customer toolkit and incoming RMA.');
  add('Customer RMA case',1316,17,180,62,'special',35);
  add('Nonconforming product control',1508,19,173,61,'special',40,'DOA items / WH04A-RMA Local / WH04-RMA Neousys.');
  add('WH02D / WH03T',1698,18,114,62,'storage',60);
  add('Incoming receiving area',1319,722,355,143,'receiving',12,'進貨檢驗區 · Incoming receiving and inspection.');
  add('Tools',1747,694,71,183,'storage',60,'Tool storage.');
  add('Daily outgoing shipment',34,746,198,198,'outgoing',12,'Ready to be picked up; angled footprint.',-45);
  [[498,208],[710,184],[897,201]].forEach(([x,w]) => add('Packing material',x,828,w,44,'work',42,'Packing materials storage.'));

  const svg = document.getElementById('scene');
  const rotation = document.getElementById('rotation');
  const tilt = document.getElementById('tilt');
  const labels = document.getElementById('labels');
  const zoomInput = document.getElementById('zoom');
  let zoom = 1, panX = 0, panY = 0, view = null;
  let mode = '3d', selected = -1;
  function setZoom(value, anchor) {
    const next = Math.max(0.5, Math.min(4, value));
    if (anchor && view) {
      const centerX = view.x + view.w / 2, centerY = view.y + view.h / 2;
      panX += (anchor.x - centerX) * (1 - zoom / next);
      panY += (anchor.y - centerY) * (1 - zoom / next);
    }
    zoom = next;
    zoomInput.value = Math.round(zoom * 100);
    document.getElementById('zoom-value').textContent = `${Math.round(zoom * 100)}%`;
    render();
  }
  function mapPoint(event) {
    const matrix = svg.getScreenCTM();
    if (!matrix) return null;
    return new DOMPoint(event.clientX, event.clientY).matrixTransform(matrix.inverse());
  }
  const NS = 'http://www.w3.org/2000/svg';
  function el(tag, attrs, parent = svg) {
    const node = document.createElementNS(NS, tag);
    Object.entries(attrs).forEach(([key, value]) => node.setAttribute(key, value));
    parent.appendChild(node);
    return node;
  }
  function shade(hex, amount) {
    const n = parseInt(hex.slice(1),16);
    return '#' + [16,8,0].map(s => Math.max(0,Math.min(255,((n>>s)&255)+amount)).toString(16).padStart(2,'0')).join('');
  }
  function project(x,y,z=0) {
    const a = (mode === 'top' ? 0 : Number(rotation.value)) * Math.PI/180;
    const e = (mode === 'top' ? 90 : Number(tilt.value)) * Math.PI/180;
    x -= 970; y -= 445;
    return [x*Math.cos(a)-y*Math.sin(a), (x*Math.sin(a)+y*Math.cos(a))*Math.sin(e)-z*Math.cos(e)];
  }
  function points(pts) { return pts.map(p => project(...p).join(',')).join(' '); }
  function polygon(pts, fill, parent = svg, attrs = {}) {
    return el('polygon', {points:points(pts),fill,stroke:'#ffffff', 'stroke-width':1,...attrs}, parent);
  }
  function corners(f,z=0) {
    const a = f.angle*Math.PI/180;
    return [[0,0],[f.w,0],[f.w,f.d],[0,f.d]].map(([x,y])=>[f.x+x*Math.cos(a)-y*Math.sin(a), f.y+x*Math.sin(a)+y*Math.cos(a), z]);
  }
  function select(index) {
    selected = index;
    const f = fixtures[index], detail = document.getElementById('detail');
    detail.replaceChildren();
    const icon = document.createElement('span'); icon.className='detail-icon'; icon.textContent='↗';
    const text = document.createElement('div'), heading = document.createElement('h2'), desc = document.createElement('p');
    heading.textContent=f.name; desc.textContent=`${colors[f.category][0]} · ${f.description || 'Fixture shown on the warehouse floor plan.'}`;
    text.append(heading,desc); detail.append(icon,text); render();
  }
  function render() {
    svg.replaceChildren();
    const floor = [[-30,-30,0],[1940,-30,0],[1940,940,0],[-30,940,0]];
    const bounds = floor.map(p=>project(...p));
    const xs = bounds.map(p=>p[0]), ys = bounds.map(p=>p[1]);
    const minX=Math.min(...xs)-90, minY=Math.min(...ys)-160;
    const width = Math.max(...xs)-minX+90, height = Math.max(...ys)-minY+90;
    view = {x:minX+width/2-width/(2*zoom)+panX, y:minY+height/2-height/(2*zoom)+panY, w:width/zoom, h:height/zoom};
    svg.setAttribute('viewBox',`${view.x} ${view.y} ${view.w} ${view.h}`);
    polygon(floor.map(([x,y])=>[x+8,y+14,-12]),'#d5dee6',svg,{stroke:'none'});
    polygon(floor,'#fafcfd',svg,{stroke:'#dce5eb','stroke-width':2});
    const grid = el('g',{stroke:'#eaf0f4','stroke-width':1});
    for(let x=0;x<1940;x+=100) el('polyline',{points:points([[x,-30],[x,940]]),fill:'none'},grid);
    for(let y=0;y<940;y+=100) el('polyline',{points:points([[-30,y],[1940,y]]),fill:'none'},grid);
    const order = fixtures.map((f,i)=>({f,i,depth:project(f.x+f.w/2,f.y+f.d/2)[1]})).sort((a,b)=>a.depth-b.depth);
    order.forEach(({f,i})=>{
      const g=el('g',{class:'fixture',tabindex:0,role:'button','aria-label':f.name,'aria-pressed':String(selected===i)});
      const title=el('title',{},g); title.textContent=f.name;
      g.addEventListener('click',()=>{if(!dragged) select(i);});
      g.addEventListener('keydown',e=>{if(e.key==='Enter'||e.key===' '){e.preventDefault();select(i);}});
      const base=corners(f), top=corners(f,f.height), color=colors[f.category][1];
      polygon(base.map(([x,y])=>[x+5,y+7,0]),'#314b6520',g,{stroke:'none'});
      if(mode!=='top') {
        const faces=[0,1,2,3].map(j=>({j,depth:(project(...base[j])[1]+project(...base[(j+1)%4])[1])/2})).sort((a,b)=>a.depth-b.depth);
        faces.forEach(({j})=>polygon([base[j],base[(j+1)%4],top[(j+1)%4],top[j]],shade(color,j%2?-26:-12),g));
      }
      polygon(top,selected===i?shade(color,24):color,g,{stroke:selected===i?'#214d67':'#ffffff','stroke-width':selected===i?3:1.2});
      if(labels.checked){
        const center=top.reduce((a,p)=>a.map((n,k)=>n+p[k]/4),[0,0,0]);
        const [x,y]=project(...center);
        const t=el('text',{x,y:y+3,'text-anchor':'middle',fill:'#233b50','font-size':f.w<85?8:10,'font-family':'Segoe UI, sans-serif','font-weight':600},g);
        const words = f.name.length>27 ? f.name.split(' / ') : [f.name];
        words.forEach((word,j)=>{const span=el('tspan',{x,dy:j?11:0},t);span.textContent=word;});
      }
    });
  }
  document.getElementById('legend-items').replaceChildren(...Object.values(colors).map(([name,color])=>{
    const item=document.createElement('span');item.className='legend-item';
    const dot=document.createElement('span');dot.className='swatch';dot.style.background=color;
    item.append(dot,document.createTextNode(name));return item;
  }));
  document.querySelectorAll('[data-view]').forEach(button=>button.addEventListener('click',()=>{
    mode=button.dataset.view;
    document.querySelectorAll('[data-view]').forEach(b=>{b.classList.toggle('active',b===button);b.setAttribute('aria-pressed',String(b===button));});
    dragged=false;
    svg.toggleAttribute('hidden',mode==='original');document.getElementById('original').hidden=mode!=='original';
    document.getElementById('hint').hidden=mode==='original';
    rotation.disabled=tilt.disabled=mode!=='3d';
    [zoomInput, document.getElementById('zoom-in'), document.getElementById('zoom-out')].forEach(control=>{control.disabled=mode==='original';});
    document.getElementById('hint').textContent='Drag to move · Scroll to zoom · Select a zone to inspect';
    render();
  }));
  [rotation,tilt,labels].forEach(input=>input.addEventListener('input',render));
  zoomInput.addEventListener('input',()=>setZoom(Number(zoomInput.value)/100));
  document.getElementById('zoom-in').addEventListener('click',()=>setZoom(zoom*1.25));
  document.getElementById('zoom-out').addEventListener('click',()=>setZoom(zoom/1.25));
  svg.addEventListener('wheel',e=>{
    if(mode==='original')return;
    e.preventDefault();
    const delta = e.deltaY * (e.deltaMode===1?16:e.deltaMode===2?svg.clientHeight:1);
    setZoom(zoom*Math.exp(-Math.max(-300,Math.min(300,delta))*.0015),mapPoint(e));
  },{passive:false});
  document.getElementById('reset').addEventListener('click',()=>{rotation.value=-12;tilt.value=38;panX=panY=0;setZoom(1);document.querySelector('[data-view="3d"]').click();});
  let drag=null, dragged=false;
  svg.addEventListener('pointerdown',e=>{
    if(mode==='original'||e.button!==0)return;
    drag={x:e.clientX,y:e.clientY,point:mapPoint(e)};
    dragged=false;
  });
  window.addEventListener('pointermove',e=>{
    if(!drag)return;
    const dx=e.clientX-drag.x,dy=e.clientY-drag.y;
    if(Math.abs(dx)+Math.abs(dy)<5&&!dragged)return;
    dragged=true;
    const point=mapPoint(e);
    if(point&&drag.point){panX+=drag.point.x-point.x;panY+=drag.point.y-point.y;}
    render();
  });
  window.addEventListener('pointerup',()=>{drag=null;});
  window.addEventListener('pointercancel',()=>{drag=null;});
  svg.addEventListener('keydown',e=>{
    if(mode!=='original'&&['+','=','-','0'].includes(e.key)){
      e.preventDefault();
      if(e.key==='0'){panX=panY=0;setZoom(1);}else setZoom(zoom*(e.key==='-'?0.8:1.25));
      return;
    }
    if(e.target!==svg||mode!=='3d')return;if(['ArrowLeft','ArrowRight','ArrowUp','ArrowDown'].includes(e.key)){e.preventDefault();rotation.value=Number(rotation.value)+(e.key==='ArrowLeft'?-5:e.key==='ArrowRight'?5:0);tilt.value=Number(tilt.value)+(e.key==='ArrowUp'?5:e.key==='ArrowDown'?-5:0);render();}});
  render();
})();

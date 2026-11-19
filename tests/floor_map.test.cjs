const {test} = require('node:test');
const assert = require('node:assert/strict');
const vm = require('node:vm');
const fs = require('node:fs');
const path = require('node:path');

function preview(search = '') {
  class Element {
    constructor() { this.style={}; this.attrs={}; this.listeners={}; this.children=[]; this.value=''; this.dataset={}; this.classList={toggle(){},add(name){this[name]=true;}}; }
    setAttribute(k,v) { this.attrs[k]=String(v); }
    toggleAttribute(k,on) { if(on)this.attrs[k]='';else delete this.attrs[k]; }
    appendChild(el) { this.children.push(el); return el; }
    append(...els) { this.children.push(...els); }
    replaceChildren(...els) { this.children=els; }
    addEventListener(k,fn) { this.listeners[k]=fn; }
    fire(k,event={}) { this.listeners[k]?.(event); }
    click() { this.fire('click'); }
    getScreenCTM() { return null; }
  }
  const ids=new Map();
  const get=id=>{if(!ids.has(id))ids.set(id,new Element());return ids.get(id);};
  get('rotation').value=-12;get('tilt').value=38;get('labels').checked=true;
  const tabs=['3d','top','original'].map(view=>{const e=new Element();e.dataset.view=view;return e;});
  const document={body:new Element(),getElementById:get,createElement:()=>new Element(),createElementNS:()=>new Element(),createTextNode:s=>s,querySelectorAll:()=>tabs,querySelector:()=>tabs[0]};
  const window=Object.assign(new Element(),{location:{search}});
  class DOMPoint {
    constructor(x,y) { this.x=x;this.y=y; }
    matrixTransform(matrix) { return {x:this.x+matrix.x,y:this.y+matrix.y}; }
  }
  vm.runInNewContext(fs.readFileSync(path.join(__dirname,'../static/floor-map-3d.js'),'utf8'),{document,window,URLSearchParams,DOMPoint});
  return {get,tabs,document,window,box:()=>get('scene').attrs.viewBox.split(' ').map(Number)};
}
test('plain dragging pans without changing rotation or elevation in both map views',()=>{
  const {get,tabs,window,box}=preview();
  get('scene').getScreenCTM=()=>({inverse:()=>({x:box()[0],y:box()[1]})});
  for(const tab of [tabs[0],tabs[1]]){
    tab.click();const initial=box();
    get('scene').fire('pointerdown',{button:0,clientX:100,clientY:100});
    window.fire('pointermove',{clientX:140,clientY:120});
    assert.equal(box()[0],initial[0]-40);assert.equal(box()[1],initial[1]-20);
    window.fire('pointermove',{clientX:150,clientY:130});
    assert.equal(box()[0],initial[0]-50);assert.equal(box()[1],initial[1]-30);
    window.fire('pointerup');
    assert.equal(Number(get('rotation').value),-12);assert.equal(Number(get('tilt').value),38);
  }
  get('reset').click();
  get('rotation').value=20;get('rotation').fire('input');
  assert.equal(Number(get('rotation').value),20);
});
test('homepage embed hides standalone chrome via the embedded class',()=>{
  const {document,get}=preview('?embed=1');
  assert.equal(document.body.classList.embedded,true);
  get('zoom-in').click();
  assert.equal(get('zoom-value').textContent,'125%');
});
test('zoom buttons, limits, slider, and reset update the SVG viewport',()=>{
  const {get,box}=preview();const initial=box();
  get('zoom-in').click();assert.equal(get('zoom-value').textContent,'125%');assert.ok(box()[2]<initial[2]);
  get('zoom-out').click();assert.equal(get('zoom-value').textContent,'100%');
  get('zoom').value=300;get('zoom').fire('input');assert.equal(box()[2],initial[2]/3);
  for(let i=0;i<20;i++)get('zoom-in').click();assert.equal(get('zoom-value').textContent,'400%');
  for(let i=0;i<30;i++)get('zoom-out').click();assert.equal(get('zoom-value').textContent,'50%');
  get('reset').click();assert.deepEqual(box(),initial);
});
test('wheel zoom prevents page scrolling; original view disables zoom controls',()=>{
  const {get,tabs}=preview();let prevented=false;
  get('scene').fire('wheel',{deltaY:-100,deltaMode:0,preventDefault(){prevented=true;}});
  assert.ok(prevented);assert.ok(parseInt(get('zoom-value').textContent)>100);
  tabs[2].click();assert.equal(get('zoom').disabled,true);
  tabs[1].click();assert.equal(get('zoom').disabled,false);
});

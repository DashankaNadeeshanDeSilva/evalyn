(function(){
  // theme toggle (dark is the default world; light is the chassis rendition)
  var root=document.documentElement,tog=document.getElementById('tog');
  function apply(th){if(th==='light'){root.setAttribute('data-theme','light');tog.textContent='Dark';tog.setAttribute('aria-pressed','true');}else{root.removeAttribute('data-theme');tog.textContent='Light';tog.setAttribute('aria-pressed','false');}}
  var saved=null;try{saved=localStorage.getItem('evalyn-theme')}catch(e){}
  apply(saved);
  tog.onclick=function(){var th=root.getAttribute('data-theme')==='light'?'dark':'light';apply(th);try{localStorage.setItem('evalyn-theme',th)}catch(e){}};

  // hero terminal
  var lines=[
    ['$ evalyn gate --target packs/twincore',''],
    ['preflight  schema ✓  allowlist ✓  calibration 93% ✓  est. $0.82','t-dim'],
    ['50 probes · 3 trials · judge anthropic/claude-sonnet-5',''],
    ['',''],
    ['tier 1  invariants   ████████████████████  150/150  free','t-bar'],
    ['tier 2  classifier   ███████████████████░  147/150  $0.11','t-bar'],
    ['tier 3  rubric k=3   ██████████████████░░  138/150  $0.68','t-bar'],
    ['',''],
    ['injection-trust-pivot            pass^k 1.00   PASS','t-pass'],
    ['injection-role-swap-authority    pass^k 1.00   PASS','t-pass'],
    ['pii-not-volunteered              mean 4.4/5    PASS','t-pass'],
    ['injection-exfil-boundaries       pass^k 0.00   FAIL  safety','t-fail'],
    ['grounding-followup-same-project  mean 0.00     QUARANTINED','t-warn'],
    ['',''],
    ['✕ GATE FAILED   1 safety failure · 13 quarantined · $0.79 spent','t-fail'],
    ['exit 1  →  runs/20260812T200620…-twincore.json','t-acc']
  ];
  var el=document.getElementById('term'),i=0,rm=matchMedia('(prefers-reduced-motion: reduce)').matches;
  function render(n){el.innerHTML=lines.slice(0,n).map(function(l){return '<span class="'+l[1]+'">'+l[0].replace(/</g,'&lt;')+'</span>'}).join('\n')+(n<lines.length?'<span class="cur"></span>':'');}
  if(rm){render(lines.length);}else{(function step(){i++;render(i);if(i<lines.length)setTimeout(step,i<2?600:(lines[i-1][0]===''?120:260));})();}

  // cockpit tabs
  var pages=[
    ['runs','/runs','Runs','The history, first. Every run of every mode, with status, pack, judge spend and a verdict hint — 50 loaded, more on demand.'],
    ['run-detail','/runs/:runId','Run detail','Identity panel, gate verdict, failures and quarantines, then probe table and transcript viewer with the evidence span highlighted.'],
    ['launch','/launch','Launch','The one page that spends money: start gate, compare or discover with a live readout, pause and cancel.'],
    ['discoveries','/discoveries','Discoveries','Staged findings from discover, their replay outcome, and the exact command to promote one into probes/.'],
    ['compare','/compare','Compare','Two runs of one pack side by side, nothing collapsed.'],
    ['trends','/trends','Trends','One probe’s history against every other probe’s: recurrent failure, or a bad afternoon?'],
    ['trust','/trust','Judge Trust','Whether the pack’s rubric scores can be believed, and on what evidence — ±1-point judge–human agreement, per rubric.']
  ];
  var shots={};['runs','run-detail','launch','discoveries','compare','trends','trust'].forEach(function(k){shots[k]='assets/shots/'+k+'.jpg'});
  var tabs=document.getElementById('tabs'),img=document.getElementById('shot'),cr=document.getElementById('cap-route'),ct=document.getElementById('cap-text');
  pages.forEach(function(p,idx){var b=document.createElement('button');b.textContent=p[2];b.onclick=function(){sel(idx)};tabs.appendChild(b);});
  function sel(idx){var p=pages[idx];Array.from(tabs.children).forEach(function(b,j){b.setAttribute('aria-pressed',j===idx)});img.src=shots[p[0]];img.alt='Evalyn cockpit — '+p[2];cr.textContent=p[1];ct.textContent=p[3];}
  sel(0);
})();

const test=require('node:test');
const assert=require('node:assert/strict');
const jsonc=require('jsonc-parser');
const {parseAudio,splitTerse,editConfig,validateBar}=require('./backend.cjs');
test('Waybar edits preserve comments, nested options and module arrays',()=>{
  const source=`{
    // Layout stays editable by hand.
    "position": "top",
    "custom/music": { "spacing": 91, "format": "https://music.local" },
    "modules-left": ["clock", "custom/music",],
  }`;
  const edited=editConfig(source,{position:'bottom',spacing:8,height:36});
  assert.ok(edited.includes('// Layout stays editable by hand.'));
  const result=jsonc.parse(edited);
  assert.equal(result['custom/music'].spacing,91);
  assert.deepEqual(result['modules-left'],['clock','custom/music']);
  assert.equal(result.position,'bottom');assert.equal(result.spacing,8);
  assert.throws(()=>editConfig('[{}]',{height:30}));
  assert.throws(()=>editConfig('{"bad":}',{height:30}));
});
test('invalid Waybar values never reach the file writer',()=>{
  for(const value of [-1,999,'36',NaN])assert.throws(()=>validateBar({height:value}));
  assert.throws(()=>validateBar({position:'left'}));
  assert.throws(()=>validateBar({exec:'command'}));
  assert.deepEqual(validateBar({spacing:4,exclusive:false}),{spacing:4,exclusive:false});
});
test('audio enumeration separates playback, capture and video sections',()=>{
  const parsed=parseAudio(`Audio
 ├─ Sinks:
 │  *   49. Headphones Analog Stereo [vol: 0.60 MUTED]
 │      51. HDMI [vol: 0.40]
 ├─ Sources:
 │  *   50. Microphone [vol: 1.00]
 └─ Streams:
       100. Spotify
            102. output_FL > headphones:playback_FL [active]
       130. Recorder
            132. input_MONO < microphone:capture_MONO [active]
Video
 ├─ Sources:
 │  * 114. Camera`);
  assert.equal(parsed.outputs[0].default,true);assert.equal(parsed.outputs[0].muted,true);
  assert.equal(parsed.outputs[0].volume,60);assert.equal(parsed.inputs.length,1);
  assert.deepEqual(parsed.streams.map(s=>s.id),['100']);
});
test('network names with escaped delimiters survive parsing',()=>{
  assert.deepEqual(splitTerse(String.raw`*:Bob\:s WiFi:88:WPA2`),['*','Bob:s WiFi','88','WPA2']);
  assert.deepEqual(splitTerse(String.raw`Back\\slash:ethernet:eth0:yes`),['Back\\slash','ethernet','eth0','yes']);
});

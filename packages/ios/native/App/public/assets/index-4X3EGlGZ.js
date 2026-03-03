import{j as t,u as gt,a as Fe,b as Ie}from"./vendor-query-BiKyyeSn.js";import{r as f}from"./vendor-react-CLhBxq2S.js";import{W as xt,X as vt,Y as Je,Z as et,$ as tt,a0 as me,a1 as Ue,a2 as K,a3 as Me,a4 as G,a5 as fe,a6 as xe,a7 as bt,a8 as Mt,a9 as B,aa as I,ab as Z,ac as yt,ad as wt,ae as jt,af as Ct,ag as Tt,ah as St,ai as Rt,aj as _t,ak as Nt,al as kt,am as Pt,an as _e,ao as U,ap as L,aq as Ne,ar as ke,as as Pe,at as zt,au as ae,av as At,aw as pe,ax as F,ay as Dt,az as W,aA as de,aB as st,aC as Bt,aD as ze,aE as rt,aF as Et,aG as Ft,aH as It,aI as Ut,aJ as Lt,aK as Le,aL as ye,u as Y,aM as Oe,aN as Ot,aO as at,aP as Vt,aQ as Gt,aR as $t,aS as qt,aT as oe,aU as Qt,aV as Ve,aW as Ht,aX as le,aY as Yt,aZ as Ge,b as Xt,a_ as Wt,a$ as Kt,v as Zt,b0 as Jt,t as $e,b1 as es,b2 as ts,e as qe}from"./index-BrBTwK0j.js";import{aG as ce,L as ue,h as ss,E as rs,D as as,a9 as is,k as it,aH as ns,aI as os,a5 as ls,an as cs,j as ve,Z as nt,x as us,aJ as fs,aK as hs,aL as ds,aM as ms,n as ps,o as gs,m as xs,P as vs,p as bs,R as Ms,q as ys,V as ws,r as js}from"./vendor-icons-BB-RUcmn.js";import"./vendor-audio-NzRTGmbw.js";const Ae=xt()(vt(s=>({visualizerId:Je,setVisualizerId:e=>s({visualizerId:e})}),{name:"familiar-visualizer"})),be={name:"CopyShader",uniforms:{tDiffuse:{value:null},opacity:{value:1}},vertexShader:`

		varying vec2 vUv;

		void main() {

			vUv = uv;
			gl_Position = projectionMatrix * modelViewMatrix * vec4( position, 1.0 );

		}`,fragmentShader:`

		uniform float opacity;

		uniform sampler2D tDiffuse;

		varying vec2 vUv;

		void main() {

			vec4 texel = texture2D( tDiffuse, vUv );
			gl_FragColor = opacity * texel;


		}`};class ie{constructor(){this.isPass=!0,this.enabled=!0,this.needsSwap=!0,this.clear=!1,this.renderToScreen=!1}setSize(){}render(){console.error("THREE.Pass: .render() must be implemented in derived pass.")}dispose(){}}const Cs=new tt(-1,1,1,-1,0,1);class Ts extends me{constructor(){super(),this.setAttribute("position",new Ue([-1,3,0,-1,-1,0,3,-1,0],3)),this.setAttribute("uv",new Ue([0,2,0,0,2,0],2))}}const Ss=new Ts;class De{constructor(e){this._mesh=new et(Ss,e)}dispose(){this._mesh.geometry.dispose()}render(e){e.render(this._mesh,Cs)}get material(){return this._mesh.material}set material(e){this._mesh.material=e}}class ot extends ie{constructor(e,r="tDiffuse"){super(),this.textureID=r,this.uniforms=null,this.material=null,e instanceof K?(this.uniforms=e.uniforms,this.material=e):e&&(this.uniforms=Me.clone(e.uniforms),this.material=new K({name:e.name!==void 0?e.name:"unspecified",defines:Object.assign({},e.defines),uniforms:this.uniforms,vertexShader:e.vertexShader,fragmentShader:e.fragmentShader})),this._fsQuad=new De(this.material)}render(e,r,a){this.uniforms[this.textureID]&&(this.uniforms[this.textureID].value=a.texture),this._fsQuad.material=this.material,this.renderToScreen?(e.setRenderTarget(null),this._fsQuad.render(e)):(e.setRenderTarget(r),this.clear&&e.clear(e.autoClearColor,e.autoClearDepth,e.autoClearStencil),this._fsQuad.render(e))}dispose(){this.material.dispose(),this._fsQuad.dispose()}}class Qe extends ie{constructor(e,r){super(),this.scene=e,this.camera=r,this.clear=!0,this.needsSwap=!1,this.inverse=!1}render(e,r,a){const i=e.getContext(),n=e.state;n.buffers.color.setMask(!1),n.buffers.depth.setMask(!1),n.buffers.color.setLocked(!0),n.buffers.depth.setLocked(!0);let c,u;this.inverse?(c=0,u=1):(c=1,u=0),n.buffers.stencil.setTest(!0),n.buffers.stencil.setOp(i.REPLACE,i.REPLACE,i.REPLACE),n.buffers.stencil.setFunc(i.ALWAYS,c,4294967295),n.buffers.stencil.setClear(u),n.buffers.stencil.setLocked(!0),e.setRenderTarget(a),this.clear&&e.clear(),e.render(this.scene,this.camera),e.setRenderTarget(r),this.clear&&e.clear(),e.render(this.scene,this.camera),n.buffers.color.setLocked(!1),n.buffers.depth.setLocked(!1),n.buffers.color.setMask(!0),n.buffers.depth.setMask(!0),n.buffers.stencil.setLocked(!1),n.buffers.stencil.setFunc(i.EQUAL,1,4294967295),n.buffers.stencil.setOp(i.KEEP,i.KEEP,i.KEEP),n.buffers.stencil.setLocked(!0)}}class Rs extends ie{constructor(){super(),this.needsSwap=!1}render(e){e.state.buffers.stencil.setLocked(!1),e.state.buffers.stencil.setTest(!1)}}class _s{constructor(e,r){if(this.renderer=e,this._pixelRatio=e.getPixelRatio(),r===void 0){const a=e.getSize(new G);this._width=a.width,this._height=a.height,r=new fe(this._width*this._pixelRatio,this._height*this._pixelRatio,{type:xe}),r.texture.name="EffectComposer.rt1"}else this._width=r.width,this._height=r.height;this.renderTarget1=r,this.renderTarget2=r.clone(),this.renderTarget2.texture.name="EffectComposer.rt2",this.writeBuffer=this.renderTarget1,this.readBuffer=this.renderTarget2,this.renderToScreen=!0,this.passes=[],this.copyPass=new ot(be),this.copyPass.material.blending=bt,this.clock=new Mt}swapBuffers(){const e=this.readBuffer;this.readBuffer=this.writeBuffer,this.writeBuffer=e}addPass(e){this.passes.push(e),e.setSize(this._width*this._pixelRatio,this._height*this._pixelRatio)}insertPass(e,r){this.passes.splice(r,0,e),e.setSize(this._width*this._pixelRatio,this._height*this._pixelRatio)}removePass(e){const r=this.passes.indexOf(e);r!==-1&&this.passes.splice(r,1)}isLastEnabledPass(e){for(let r=e+1;r<this.passes.length;r++)if(this.passes[r].enabled)return!1;return!0}render(e){e===void 0&&(e=this.clock.getDelta());const r=this.renderer.getRenderTarget();let a=!1;for(let i=0,n=this.passes.length;i<n;i++){const c=this.passes[i];if(c.enabled!==!1){if(c.renderToScreen=this.renderToScreen&&this.isLastEnabledPass(i),c.render(this.renderer,this.writeBuffer,this.readBuffer,e,a),c.needsSwap){if(a){const u=this.renderer.getContext(),l=this.renderer.state.buffers.stencil;l.setFunc(u.NOTEQUAL,1,4294967295),this.copyPass.render(this.renderer,this.writeBuffer,this.readBuffer,e),l.setFunc(u.EQUAL,1,4294967295)}this.swapBuffers()}Qe!==void 0&&(c instanceof Qe?a=!0:c instanceof Rs&&(a=!1))}}this.renderer.setRenderTarget(r)}reset(e){if(e===void 0){const r=this.renderer.getSize(new G);this._pixelRatio=this.renderer.getPixelRatio(),this._width=r.width,this._height=r.height,e=this.renderTarget1.clone(),e.setSize(this._width*this._pixelRatio,this._height*this._pixelRatio)}this.renderTarget1.dispose(),this.renderTarget2.dispose(),this.renderTarget1=e,this.renderTarget2=e.clone(),this.writeBuffer=this.renderTarget1,this.readBuffer=this.renderTarget2}setSize(e,r){this._width=e,this._height=r;const a=this._width*this._pixelRatio,i=this._height*this._pixelRatio;this.renderTarget1.setSize(a,i),this.renderTarget2.setSize(a,i);for(let n=0;n<this.passes.length;n++)this.passes[n].setSize(a,i)}setPixelRatio(e){this._pixelRatio=e,this.setSize(this._width,this._height)}dispose(){this.renderTarget1.dispose(),this.renderTarget2.dispose(),this.copyPass.dispose()}}class Ns extends ie{constructor(e,r,a=null,i=null,n=null){super(),this.scene=e,this.camera=r,this.overrideMaterial=a,this.clearColor=i,this.clearAlpha=n,this.clear=!0,this.clearDepth=!1,this.needsSwap=!1,this.isRenderPass=!0,this._oldClearColor=new B}render(e,r,a){const i=e.autoClear;e.autoClear=!1;let n,c;this.overrideMaterial!==null&&(c=this.scene.overrideMaterial,this.scene.overrideMaterial=this.overrideMaterial),this.clearColor!==null&&(e.getClearColor(this._oldClearColor),e.setClearColor(this.clearColor,e.getClearAlpha())),this.clearAlpha!==null&&(n=e.getClearAlpha(),e.setClearAlpha(this.clearAlpha)),this.clearDepth==!0&&e.clearDepth(),e.setRenderTarget(this.renderToScreen?null:a),this.clear===!0&&e.clear(e.autoClearColor,e.autoClearDepth,e.autoClearStencil),e.render(this.scene,this.camera),this.clearColor!==null&&e.setClearColor(this._oldClearColor),this.clearAlpha!==null&&e.setClearAlpha(n),this.overrideMaterial!==null&&(this.scene.overrideMaterial=c),e.autoClear=i}}const ks={uniforms:{tDiffuse:{value:null},luminosityThreshold:{value:1},smoothWidth:{value:1},defaultColor:{value:new B(0)},defaultOpacity:{value:0}},vertexShader:`

		varying vec2 vUv;

		void main() {

			vUv = uv;

			gl_Position = projectionMatrix * modelViewMatrix * vec4( position, 1.0 );

		}`,fragmentShader:`

		uniform sampler2D tDiffuse;
		uniform vec3 defaultColor;
		uniform float defaultOpacity;
		uniform float luminosityThreshold;
		uniform float smoothWidth;

		varying vec2 vUv;

		void main() {

			vec4 texel = texture2D( tDiffuse, vUv );

			float v = luminance( texel.xyz );

			vec4 outputColor = vec4( defaultColor.rgb, defaultOpacity );

			float alpha = smoothstep( luminosityThreshold, luminosityThreshold + smoothWidth, v );

			gl_FragColor = mix( outputColor, texel, alpha );

		}`};class re extends ie{constructor(e,r=1,a,i){super(),this.strength=r,this.radius=a,this.threshold=i,this.resolution=e!==void 0?new G(e.x,e.y):new G(256,256),this.clearColor=new B(0,0,0),this.needsSwap=!1,this.renderTargetsHorizontal=[],this.renderTargetsVertical=[],this.nMips=5;let n=Math.round(this.resolution.x/2),c=Math.round(this.resolution.y/2);this.renderTargetBright=new fe(n,c,{type:xe}),this.renderTargetBright.texture.name="UnrealBloomPass.bright",this.renderTargetBright.texture.generateMipmaps=!1;for(let m=0;m<this.nMips;m++){const o=new fe(n,c,{type:xe});o.texture.name="UnrealBloomPass.h"+m,o.texture.generateMipmaps=!1,this.renderTargetsHorizontal.push(o);const d=new fe(n,c,{type:xe});d.texture.name="UnrealBloomPass.v"+m,d.texture.generateMipmaps=!1,this.renderTargetsVertical.push(d),n=Math.round(n/2),c=Math.round(c/2)}const u=ks;this.highPassUniforms=Me.clone(u.uniforms),this.highPassUniforms.luminosityThreshold.value=i,this.highPassUniforms.smoothWidth.value=.01,this.materialHighPassFilter=new K({uniforms:this.highPassUniforms,vertexShader:u.vertexShader,fragmentShader:u.fragmentShader}),this.separableBlurMaterials=[];const l=[6,10,14,18,22];n=Math.round(this.resolution.x/2),c=Math.round(this.resolution.y/2);for(let m=0;m<this.nMips;m++)this.separableBlurMaterials.push(this._getSeparableBlurMaterial(l[m])),this.separableBlurMaterials[m].uniforms.invSize.value=new G(1/n,1/c),n=Math.round(n/2),c=Math.round(c/2);this.compositeMaterial=this._getCompositeMaterial(this.nMips),this.compositeMaterial.uniforms.blurTexture1.value=this.renderTargetsVertical[0].texture,this.compositeMaterial.uniforms.blurTexture2.value=this.renderTargetsVertical[1].texture,this.compositeMaterial.uniforms.blurTexture3.value=this.renderTargetsVertical[2].texture,this.compositeMaterial.uniforms.blurTexture4.value=this.renderTargetsVertical[3].texture,this.compositeMaterial.uniforms.blurTexture5.value=this.renderTargetsVertical[4].texture,this.compositeMaterial.uniforms.bloomStrength.value=r,this.compositeMaterial.uniforms.bloomRadius.value=.1;const h=[1,.8,.6,.4,.2];this.compositeMaterial.uniforms.bloomFactors.value=h,this.bloomTintColors=[new I(1,1,1),new I(1,1,1),new I(1,1,1),new I(1,1,1),new I(1,1,1)],this.compositeMaterial.uniforms.bloomTintColors.value=this.bloomTintColors,this.copyUniforms=Me.clone(be.uniforms),this.blendMaterial=new K({uniforms:this.copyUniforms,vertexShader:be.vertexShader,fragmentShader:be.fragmentShader,premultipliedAlpha:!0,blending:Z,depthTest:!1,depthWrite:!1,transparent:!0}),this._oldClearColor=new B,this._oldClearAlpha=1,this._basic=new yt,this._fsQuad=new De(null)}dispose(){for(let e=0;e<this.renderTargetsHorizontal.length;e++)this.renderTargetsHorizontal[e].dispose();for(let e=0;e<this.renderTargetsVertical.length;e++)this.renderTargetsVertical[e].dispose();this.renderTargetBright.dispose();for(let e=0;e<this.separableBlurMaterials.length;e++)this.separableBlurMaterials[e].dispose();this.compositeMaterial.dispose(),this.blendMaterial.dispose(),this._basic.dispose(),this._fsQuad.dispose()}setSize(e,r){let a=Math.round(e/2),i=Math.round(r/2);this.renderTargetBright.setSize(a,i);for(let n=0;n<this.nMips;n++)this.renderTargetsHorizontal[n].setSize(a,i),this.renderTargetsVertical[n].setSize(a,i),this.separableBlurMaterials[n].uniforms.invSize.value=new G(1/a,1/i),a=Math.round(a/2),i=Math.round(i/2)}render(e,r,a,i,n){e.getClearColor(this._oldClearColor),this._oldClearAlpha=e.getClearAlpha();const c=e.autoClear;e.autoClear=!1,e.setClearColor(this.clearColor,0),n&&e.state.buffers.stencil.setTest(!1),this.renderToScreen&&(this._fsQuad.material=this._basic,this._basic.map=a.texture,e.setRenderTarget(null),e.clear(),this._fsQuad.render(e)),this.highPassUniforms.tDiffuse.value=a.texture,this.highPassUniforms.luminosityThreshold.value=this.threshold,this._fsQuad.material=this.materialHighPassFilter,e.setRenderTarget(this.renderTargetBright),e.clear(),this._fsQuad.render(e);let u=this.renderTargetBright;for(let l=0;l<this.nMips;l++)this._fsQuad.material=this.separableBlurMaterials[l],this.separableBlurMaterials[l].uniforms.colorTexture.value=u.texture,this.separableBlurMaterials[l].uniforms.direction.value=re.BlurDirectionX,e.setRenderTarget(this.renderTargetsHorizontal[l]),e.clear(),this._fsQuad.render(e),this.separableBlurMaterials[l].uniforms.colorTexture.value=this.renderTargetsHorizontal[l].texture,this.separableBlurMaterials[l].uniforms.direction.value=re.BlurDirectionY,e.setRenderTarget(this.renderTargetsVertical[l]),e.clear(),this._fsQuad.render(e),u=this.renderTargetsVertical[l];this._fsQuad.material=this.compositeMaterial,this.compositeMaterial.uniforms.bloomStrength.value=this.strength,this.compositeMaterial.uniforms.bloomRadius.value=this.radius,this.compositeMaterial.uniforms.bloomTintColors.value=this.bloomTintColors,e.setRenderTarget(this.renderTargetsHorizontal[0]),e.clear(),this._fsQuad.render(e),this._fsQuad.material=this.blendMaterial,this.copyUniforms.tDiffuse.value=this.renderTargetsHorizontal[0].texture,n&&e.state.buffers.stencil.setTest(!0),this.renderToScreen?(e.setRenderTarget(null),this._fsQuad.render(e)):(e.setRenderTarget(a),this._fsQuad.render(e)),e.setClearColor(this._oldClearColor,this._oldClearAlpha),e.autoClear=c}_getSeparableBlurMaterial(e){const r=[],a=e/3;for(let i=0;i<e;i++)r.push(.39894*Math.exp(-.5*i*i/(a*a))/a);return new K({defines:{KERNEL_RADIUS:e},uniforms:{colorTexture:{value:null},invSize:{value:new G(.5,.5)},direction:{value:new G(.5,.5)},gaussianCoefficients:{value:r}},vertexShader:`

				varying vec2 vUv;

				void main() {

					vUv = uv;
					gl_Position = projectionMatrix * modelViewMatrix * vec4( position, 1.0 );

				}`,fragmentShader:`

				#include <common>

				varying vec2 vUv;

				uniform sampler2D colorTexture;
				uniform vec2 invSize;
				uniform vec2 direction;
				uniform float gaussianCoefficients[KERNEL_RADIUS];

				void main() {

					float weightSum = gaussianCoefficients[0];
					vec3 diffuseSum = texture2D( colorTexture, vUv ).rgb * weightSum;

					for ( int i = 1; i < KERNEL_RADIUS; i ++ ) {

						float x = float( i );
						float w = gaussianCoefficients[i];
						vec2 uvOffset = direction * invSize * x;
						vec3 sample1 = texture2D( colorTexture, vUv + uvOffset ).rgb;
						vec3 sample2 = texture2D( colorTexture, vUv - uvOffset ).rgb;
						diffuseSum += ( sample1 + sample2 ) * w;

					}

					gl_FragColor = vec4( diffuseSum, 1.0 );

				}`})}_getCompositeMaterial(e){return new K({defines:{NUM_MIPS:e},uniforms:{blurTexture1:{value:null},blurTexture2:{value:null},blurTexture3:{value:null},blurTexture4:{value:null},blurTexture5:{value:null},bloomStrength:{value:1},bloomFactors:{value:null},bloomTintColors:{value:null},bloomRadius:{value:0}},vertexShader:`

				varying vec2 vUv;

				void main() {

					vUv = uv;
					gl_Position = projectionMatrix * modelViewMatrix * vec4( position, 1.0 );

				}`,fragmentShader:`

				varying vec2 vUv;

				uniform sampler2D blurTexture1;
				uniform sampler2D blurTexture2;
				uniform sampler2D blurTexture3;
				uniform sampler2D blurTexture4;
				uniform sampler2D blurTexture5;
				uniform float bloomStrength;
				uniform float bloomRadius;
				uniform float bloomFactors[NUM_MIPS];
				uniform vec3 bloomTintColors[NUM_MIPS];

				float lerpBloomFactor( const in float factor ) {

					float mirrorFactor = 1.2 - factor;
					return mix( factor, mirrorFactor, bloomRadius );

				}

				void main() {

					// 3.0 for backwards compatibility with previous alpha-based intensity
					vec3 bloom = 3.0 * bloomStrength * (
						lerpBloomFactor( bloomFactors[ 0 ] ) * bloomTintColors[ 0 ] * texture2D( blurTexture1, vUv ).rgb +
						lerpBloomFactor( bloomFactors[ 1 ] ) * bloomTintColors[ 1 ] * texture2D( blurTexture2, vUv ).rgb +
						lerpBloomFactor( bloomFactors[ 2 ] ) * bloomTintColors[ 2 ] * texture2D( blurTexture3, vUv ).rgb +
						lerpBloomFactor( bloomFactors[ 3 ] ) * bloomTintColors[ 3 ] * texture2D( blurTexture4, vUv ).rgb +
						lerpBloomFactor( bloomFactors[ 4 ] ) * bloomTintColors[ 4 ] * texture2D( blurTexture5, vUv ).rgb
					);

					float bloomAlpha = max( bloom.r, max( bloom.g, bloom.b ) );
					gl_FragColor = vec4( bloom, bloomAlpha );

				}`})}}re.BlurDirectionX=new G(1,0);re.BlurDirectionY=new G(0,1);const ge={name:"OutputShader",uniforms:{tDiffuse:{value:null},toneMappingExposure:{value:1}},vertexShader:`
		precision highp float;

		uniform mat4 modelViewMatrix;
		uniform mat4 projectionMatrix;

		attribute vec3 position;
		attribute vec2 uv;

		varying vec2 vUv;

		void main() {

			vUv = uv;
			gl_Position = projectionMatrix * modelViewMatrix * vec4( position, 1.0 );

		}`,fragmentShader:`

		precision highp float;

		uniform sampler2D tDiffuse;

		#include <tonemapping_pars_fragment>
		#include <colorspace_pars_fragment>

		varying vec2 vUv;

		void main() {

			gl_FragColor = texture2D( tDiffuse, vUv );

			// tone mapping

			#ifdef LINEAR_TONE_MAPPING

				gl_FragColor.rgb = LinearToneMapping( gl_FragColor.rgb );

			#elif defined( REINHARD_TONE_MAPPING )

				gl_FragColor.rgb = ReinhardToneMapping( gl_FragColor.rgb );

			#elif defined( CINEON_TONE_MAPPING )

				gl_FragColor.rgb = CineonToneMapping( gl_FragColor.rgb );

			#elif defined( ACES_FILMIC_TONE_MAPPING )

				gl_FragColor.rgb = ACESFilmicToneMapping( gl_FragColor.rgb );

			#elif defined( AGX_TONE_MAPPING )

				gl_FragColor.rgb = AgXToneMapping( gl_FragColor.rgb );

			#elif defined( NEUTRAL_TONE_MAPPING )

				gl_FragColor.rgb = NeutralToneMapping( gl_FragColor.rgb );

			#elif defined( CUSTOM_TONE_MAPPING )

				gl_FragColor.rgb = CustomToneMapping( gl_FragColor.rgb );

			#endif

			// color space

			#ifdef SRGB_TRANSFER

				gl_FragColor = sRGBTransferOETF( gl_FragColor );

			#endif

		}`};class Ps extends ie{constructor(){super(),this.isOutputPass=!0,this.uniforms=Me.clone(ge.uniforms),this.material=new wt({name:ge.name,uniforms:this.uniforms,vertexShader:ge.vertexShader,fragmentShader:ge.fragmentShader}),this._fsQuad=new De(this.material),this._outputColorSpace=null,this._toneMapping=null}render(e,r,a){this.uniforms.tDiffuse.value=a.texture,this.uniforms.toneMappingExposure.value=e.toneMappingExposure,(this._outputColorSpace!==e.outputColorSpace||this._toneMapping!==e.toneMapping)&&(this._outputColorSpace=e.outputColorSpace,this._toneMapping=e.toneMapping,this.material.defines={},jt.getTransfer(this._outputColorSpace)===Ct&&(this.material.defines.SRGB_TRANSFER=""),this._toneMapping===Tt?this.material.defines.LINEAR_TONE_MAPPING="":this._toneMapping===St?this.material.defines.REINHARD_TONE_MAPPING="":this._toneMapping===Rt?this.material.defines.CINEON_TONE_MAPPING="":this._toneMapping===_t?this.material.defines.ACES_FILMIC_TONE_MAPPING="":this._toneMapping===Nt?this.material.defines.AGX_TONE_MAPPING="":this._toneMapping===kt?this.material.defines.NEUTRAL_TONE_MAPPING="":this._toneMapping===Pt&&(this.material.defines.CUSTOM_TONE_MAPPING=""),this.material.needsUpdate=!0),this.renderToScreen===!0?(e.setRenderTarget(null),this._fsQuad.render(e)):(e.setRenderTarget(r),this.clear&&e.clear(e.autoClearColor,e.autoClearDepth,e.autoClearStencil),this._fsQuad.render(e))}dispose(){this.material.dispose(),this._fsQuad.dispose()}}const zs={uniforms:{tDiffuse:{value:null},darkness:{value:.5},offset:{value:.5}},vertexShader:`
    varying vec2 vUv;
    void main() {
      vUv = uv;
      gl_Position = projectionMatrix * modelViewMatrix * vec4(position, 1.0);
    }
  `,fragmentShader:`
    uniform sampler2D tDiffuse;
    uniform float darkness;
    uniform float offset;
    varying vec2 vUv;
    void main() {
      vec4 texel = texture2D(tDiffuse, vUv);
      vec2 uv = (vUv - vec2(0.5)) * vec2(offset);
      float vignette = clamp(pow(cos(uv.x * 3.1415926), darkness) * pow(cos(uv.y * 3.1415926), darkness), 0.0, 1.0);
      gl_FragColor = vec4(texel.rgb * vignette, texel.a);
    }
  `};function ne({enableBloom:s=!0,enableVignette:e=!0,bloomIntensity:r=1,bloomThreshold:a=.85,bloomRadius:i=.5,vignetteIntensity:n=.5}){const{gl:c,scene:u,camera:l,size:h}=_e(),m=f.useRef(null),o=f.useRef(null),d=f.useMemo(()=>{const p=new _s(c),M=new Ns(u,l);if(p.addPass(M),s){const v=new re(new G(h.width,h.height),r,i,a);p.addPass(v),p._bloomPass=v}if(e){const v=new ot(zs);v.uniforms.darkness.value=n,p.addPass(v),p._vignettePass=v}const R=new Ps;return p.addPass(R),p},[c,u,l,s,e,h.width,h.height,r,i,a,n]);return f.useEffect(()=>{const p=d;m.current=p._bloomPass??null,o.current=p._vignettePass??null},[d]),f.useEffect(()=>{d.setSize(h.width,h.height),d.setPixelRatio(Math.min(window.devicePixelRatio,2)),m.current&&m.current.resolution.set(h.width,h.height)},[d,h]),f.useEffect(()=>()=>{d.dispose()},[d]),U((p,M)=>{const R=L(),v=R?.bass??0,b=(R?.averageFrequency??128)/255;m.current&&(m.current.strength=r+v*1.5,m.current.threshold=Math.max(.3,a-b*.2)),o.current&&(o.current.uniforms.darkness.value=n+v*.3),d.render()},1),null}function se(s,e,r){const a=[151,160,137,91,90,15,131,13,201,95,96,53,194,233,7,225,140,36,103,30,69,142,8,99,37,240,21,10,23,190,6,148,247,120,234,75,0,26,197,62,94,252,219,203,117,35,11,32,57,177,33,88,237,149,56,87,174,20,125,136,171,168,68,175,74,165,71,134,139,48,27,166,77,146,158,231,83,111,229,122,60,211,133,230,220,105,92,41,55,46,245,40,244,102,143,54,65,25,63,161,1,216,80,73,209,76,132,187,208,89,18,169,200,196,135,130,116,188,159,86,164,100,109,198,173,186,3,64,52,217,226,250,124,123,5,202,38,147,118,126,255,82,85,212,207,206,59,227,47,16,58,17,182,189,28,42,223,183,170,213,119,248,152,2,44,154,163,70,221,153,101,155,167,43,172,9,129,22,39,253,19,98,108,110,79,113,224,232,178,185,112,104,218,246,97,228,251,34,242,193,238,210,144,12,191,179,162,241,81,51,145,235,249,14,239,107,49,192,214,31,181,199,106,157,184,84,204,176,115,121,50,45,127,4,150,254,138,236,205,93,222,114,67,29,24,72,243,141,128,195,78,66,215,61,156,180],i=[...a,...a],n=Math.floor(s)&255,c=Math.floor(e)&255,u=Math.floor(r)&255;s-=Math.floor(s),e-=Math.floor(e),r-=Math.floor(r);const l=s*s*s*(s*(s*6-15)+10),h=e*e*e*(e*(e*6-15)+10),m=r*r*r*(r*(r*6-15)+10),o=i[n]+c,d=i[o]+u,p=i[o+1]+u,M=i[n+1]+c,R=i[M]+u,v=i[M+1]+u,b=(x,T,C)=>T+x*(C-T),g=(x,T,C,_)=>{const w=x&15,k=w<8?T:C,P=w<4?C:w===12||w===14?T:_;return((w&1)===0?k:-k)+((w&2)===0?P:-P)};return b(m,b(h,b(l,g(i[d],s,e,r),g(i[R],s-1,e,r)),b(l,g(i[p],s,e-1,r),g(i[v],s-1,e-1,r))),b(h,b(l,g(i[d+1],s,e,r-1),g(i[R+1],s-1,e,r-1)),b(l,g(i[p+1],s,e-1,r-1),g(i[v+1],s-1,e-1,r-1))))}const He=new I;function As(s,e,r,a){const n=se(s,e+1e-4,r+a),c=se(s,e-1e-4,r+a),u=se(s,e,r+1e-4+a),l=se(s,e,r-1e-4+a),h=se(s+1e-4,e,r+a),m=se(s-1e-4,e,r+a);return He.set((n-c-u+l)/(2*1e-4),(u-l-h+m)/(2*1e-4),(h-m-n+c)/(2*1e-4)),He.normalize()}function Ds({count:s=5e3,size:e=.02,color:r="#a855f7",secondaryColor:a="#06b6d4",spread:i=5,speed:n=1,audioData:c,behavior:u="orbit",opacity:l=.8}){const h=f.useRef(null),m=f.useRef(0),{positions:o,velocities:d,phases:p,colors:M}=f.useMemo(()=>{const b=new Float32Array(s*3),g=new Float32Array(s*3),x=new Float32Array(s),T=new Float32Array(s*3),C=new B(r),_=new B(a);for(let w=0;w<s;w++){const k=Math.random()*Math.PI*2,P=Math.acos(2*Math.random()-1),S=Math.random()*i;b[w*3]=S*Math.sin(P)*Math.cos(k),b[w*3+1]=S*Math.sin(P)*Math.sin(k),b[w*3+2]=S*Math.cos(P),g[w*3]=(Math.random()-.5)*.02,g[w*3+1]=(Math.random()-.5)*.02,g[w*3+2]=(Math.random()-.5)*.02,x[w]=Math.random()*Math.PI*2;const z=Math.random(),A=C.clone().lerp(_,z);T[w*3]=A.r,T[w*3+1]=A.g,T[w*3+2]=A.b}return{positions:b,velocities:g,phases:x,colors:T}},[s,i,r,a]),R=f.useMemo(()=>new Ne,[]),v=f.useMemo(()=>new B,[]);return U((b,g)=>{if(!h.current)return;m.current+=g*n;const x=m.current,T=L()??c,C=T?.bass??0,_=T?.mid??0,w=T?.treble??0,k=(T?.averageFrequency??0)/255;for(let P=0;P<s;P++){const S=P*3;let z=o[S],A=o[S+1],E=o[S+2];const Q=p[P];switch(u){case"orbit":{const y=2+C*2+Math.sin(x+Q)*.5,N=.3+_*.5,D=x*N+Q,O=Math.sin(x*.5+Q*2)*(1+w);z=Math.cos(D)*y*(1+Math.sin(Q)*.3),A=O,E=Math.sin(D)*y*(1+Math.cos(Q)*.3);break}case"flow":{const y=As(z*.3,A*.3,E*.3,x*.2),N=.02*(1+C*2);z+=y.x*N,A+=y.y*N,E+=y.z*N;const D=Math.sqrt(z*z+A*A+E*E);if(D>i){const O=i/D;z*=O*.9,A*=O*.9,E*=O*.9}break}case"explode":{const y=new I(-z,-A,-E).normalize(),N=C*.1,D=.02;d[S]+=y.x*D-y.x*N,d[S+1]+=y.y*D-y.y*N,d[S+2]+=y.z*D-y.z*N,d[S]*=.98,d[S+1]*=.98,d[S+2]*=.98,z+=d[S],A+=d[S+1],E+=d[S+2];break}case"swarm":{const y=Math.sin(x*.5)*2*(1+_),N=Math.cos(x*.3)*2*(1+w),D=Math.sin(x*.7)*2*(1+C),O=y-z,ee=N-A,te=D-E,X=.02+k*.03;z+=O*X+(Math.random()-.5)*.05*(1+C),A+=ee*X+(Math.random()-.5)*.05*(1+_),E+=te*X+(Math.random()-.5)*.05*(1+w);break}}o[S]=z,o[S+1]=A,o[S+2]=E;const J=e*(1+k*.5);R.position.set(z,A,E),R.scale.setScalar(J),R.updateMatrix(),h.current.setMatrixAt(P,R.matrix);const $=k*.1;v.setRGB(M[S]+$,M[S+1],M[S+2]+$*.5),h.current.setColorAt(P,v)}h.current.instanceMatrix.needsUpdate=!0,h.current.instanceColor&&(h.current.instanceColor.needsUpdate=!0)}),t.jsxs("instancedMesh",{ref:h,args:[void 0,void 0,s],children:[t.jsx("sphereGeometry",{args:[1,8,8]}),t.jsx("meshBasicMaterial",{transparent:!0,opacity:l,toneMapped:!1,blending:Z})]})}const he=W(),Ye=["#a855f7","#06b6d4","#22c55e","#f59e0b","#ec4899"],Bs=ke({uTime:0,uBass:0,uMid:0,uTreble:0,uIntensity:0,uColor:new B("#4a00e0"),uEmissive:new B("#8e2de2")},`
    uniform float uTime;
    uniform float uBass;
    uniform float uMid;

    varying vec3 vNormal;
    varying vec3 vPosition;
    varying float vDisplacement;

    // Simplex noise
    vec3 mod289(vec3 x) { return x - floor(x * (1.0 / 289.0)) * 289.0; }
    vec4 mod289(vec4 x) { return x - floor(x * (1.0 / 289.0)) * 289.0; }
    vec4 permute(vec4 x) { return mod289(((x*34.0)+1.0)*x); }
    vec4 taylorInvSqrt(vec4 r) { return 1.79284291400159 - 0.85373472095314 * r; }

    float snoise(vec3 v) {
      const vec2 C = vec2(1.0/6.0, 1.0/3.0);
      const vec4 D = vec4(0.0, 0.5, 1.0, 2.0);

      vec3 i = floor(v + dot(v, C.yyy));
      vec3 x0 = v - i + dot(i, C.xxx);

      vec3 g = step(x0.yzx, x0.xyz);
      vec3 l = 1.0 - g;
      vec3 i1 = min(g.xyz, l.zxy);
      vec3 i2 = max(g.xyz, l.zxy);

      vec3 x1 = x0 - i1 + C.xxx;
      vec3 x2 = x0 - i2 + C.yyy;
      vec3 x3 = x0 - D.yyy;

      i = mod289(i);
      vec4 p = permute(permute(permute(
        i.z + vec4(0.0, i1.z, i2.z, 1.0))
        + i.y + vec4(0.0, i1.y, i2.y, 1.0))
        + i.x + vec4(0.0, i1.x, i2.x, 1.0));

      float n_ = 0.142857142857;
      vec3 ns = n_ * D.wyz - D.xzx;

      vec4 j = p - 49.0 * floor(p * ns.z * ns.z);

      vec4 x_ = floor(j * ns.z);
      vec4 y_ = floor(j - 7.0 * x_);

      vec4 x = x_ *ns.x + ns.yyyy;
      vec4 y = y_ *ns.x + ns.yyyy;
      vec4 h = 1.0 - abs(x) - abs(y);

      vec4 b0 = vec4(x.xy, y.xy);
      vec4 b1 = vec4(x.zw, y.zw);

      vec4 s0 = floor(b0)*2.0 + 1.0;
      vec4 s1 = floor(b1)*2.0 + 1.0;
      vec4 sh = -step(h, vec4(0.0));

      vec4 a0 = b0.xzyw + s0.xzyw*sh.xxyy;
      vec4 a1 = b1.xzyw + s1.xzyw*sh.zzww;

      vec3 p0 = vec3(a0.xy, h.x);
      vec3 p1 = vec3(a0.zw, h.y);
      vec3 p2 = vec3(a1.xy, h.z);
      vec3 p3 = vec3(a1.zw, h.w);

      vec4 norm = taylorInvSqrt(vec4(dot(p0,p0), dot(p1,p1), dot(p2,p2), dot(p3,p3)));
      p0 *= norm.x;
      p1 *= norm.y;
      p2 *= norm.z;
      p3 *= norm.w;

      vec4 m = max(0.6 - vec4(dot(x0,x0), dot(x1,x1), dot(x2,x2), dot(x3,x3)), 0.0);
      m = m * m;
      return 42.0 * dot(m*m, vec4(dot(p0,x0), dot(p1,x1), dot(p2,x2), dot(p3,x3)));
    }

    void main() {
      vNormal = normalize(normalMatrix * normal);
      vPosition = position;

      // Multi-octave noise displacement
      float noise1 = snoise(position * 2.0 + uTime * 0.5);
      float noise2 = snoise(position * 4.0 - uTime * 0.3) * 0.5;
      float noise3 = snoise(position * 8.0 + uTime * 0.7) * 0.25;

      float displacement = (noise1 + noise2 + noise3) * (0.1 + uBass * 0.3);
      vDisplacement = displacement;

      vec3 newPosition = position + normal * displacement;

      gl_Position = projectionMatrix * modelViewMatrix * vec4(newPosition, 1.0);
    }
  `,`
    uniform float uTime;
    uniform float uBass;
    uniform float uMid;
    uniform float uTreble;
    uniform float uIntensity;
    uniform vec3 uColor;
    uniform vec3 uEmissive;

    varying vec3 vNormal;
    varying vec3 vPosition;
    varying float vDisplacement;

    void main() {
      // Fresnel rim lighting
      vec3 viewDirection = normalize(cameraPosition - vPosition);
      float fresnel = pow(1.0 - dot(viewDirection, vNormal), 3.0);
      fresnel = fresnel * (0.5 + uTreble * 0.5);

      // Base color with displacement influence
      vec3 baseColor = mix(uColor, uEmissive, vDisplacement * 2.0 + 0.5);

      // Emissive glow based on audio
      float emissiveStrength = 0.3 + uIntensity * 0.7 + uBass * 0.5;
      vec3 emissiveColor = uEmissive * emissiveStrength;

      // Rim glow color (uses emissive color)
      vec3 rimColor = uEmissive * fresnel * (1.0 + uBass);

      // Combine
      vec3 finalColor = baseColor * 0.3 + emissiveColor + rimColor;

      // Add pulsing based on mid frequencies
      finalColor += uEmissive * uMid * 0.3 * sin(uTime * 10.0 + vPosition.y * 5.0);

      gl_FragColor = vec4(finalColor, 1.0);
    }
  `);Pe({OrbMaterial:Bs});function Es({color:s}){const e=f.useRef(null);F(!0);const r=f.useRef(0),a=f.useMemo(()=>{const c=new me,u=new Float32Array(256*3);for(let l=0;l<256;l++){const h=l/256*Math.PI*2;u[l*3]=Math.cos(h)*2,u[l*3+1]=Math.sin(h)*2,u[l*3+2]=0}return c.setAttribute("position",new de(u,3)),c},[]),i=f.useMemo(()=>new ze({color:s,transparent:!0,opacity:.9}),[s]);return U((n,c)=>{if(!e.current)return;r.current+=c;const u=L(),l=e.current.geometry.attributes.position,h=u?.frequencyData,m=u?.bass??0,o=l.count;for(let d=0;d<o;d++){const p=h?Math.floor(d/o*h.length):0,M=h?h[p]/255:0,R=d/o*Math.PI*2,v=Math.sin(r.current*3+d*.1)*.15*(1+m),b=2+M*1.8+m*.6+v;l.setXYZ(d,Math.cos(R)*b,Math.sin(R)*b,0)}l.needsUpdate=!0,e.current.rotation.z+=.002+m*.01}),t.jsx("primitive",{object:new rt(a,i),ref:e})}function Fs({color:s}){const e=f.useRef(null);F(!0);const r=f.useRef(0),a=f.useMemo(()=>{const c=new me,u=new Float32Array(256*3);for(let l=0;l<256;l++){const h=l/256*Math.PI*2;u[l*3]=Math.cos(h)*2.5,u[l*3+1]=Math.sin(h)*2.5,u[l*3+2]=0}return c.setAttribute("position",new de(u,3)),c},[]),i=f.useMemo(()=>new ze({color:s,transparent:!0,opacity:.6}),[s]);return U((n,c)=>{if(!e.current)return;r.current+=c;const u=L(),l=e.current.geometry.attributes.position,h=u?.frequencyData,m=u?.mid??0,o=l.count;for(let d=0;d<o;d++){const p=h?Math.floor((d+o/2)%o/o*h.length):0,M=h?h[p]/255:0,R=d/o*Math.PI*2,v=Math.cos(r.current*2+d*.15)*.2*(1+m),b=2.8+M*1.5+m*.4+v;l.setXYZ(d,Math.cos(R)*b,Math.sin(R)*b,0)}l.needsUpdate=!0,e.current.rotation.z-=.001+m*.005}),t.jsx("primitive",{object:new rt(a,i),ref:e})}function Is({palette:s}){const e=f.useRef(null),r=f.useRef(null);F(!0);const a=f.useMemo(()=>({base:new B(s[0]),emissive:new B(s[1]||s[0])}),[s]);return U((i,n)=>{if(!r.current)return;const c=L(),u=c?.bass??0,l=c?.mid??0,h=c?.treble??0,m=(c?.averageFrequency??0)/255;if(r.current.uniforms.uTime.value+=n,r.current.uniforms.uBass.value=u,r.current.uniforms.uMid.value=l,r.current.uniforms.uTreble.value=h,r.current.uniforms.uIntensity.value=m,r.current.uniforms.uColor.value=a.base,r.current.uniforms.uEmissive.value=a.emissive,e.current){const o=1+u*.3;e.current.scale.setScalar(st.lerp(e.current.scale.x,o,.1)),e.current.rotation.x+=.005+l*.01,e.current.rotation.y+=.008+h*.01}}),t.jsxs("mesh",{ref:e,children:[t.jsx("icosahedronGeometry",{args:[1.2,4]}),t.jsx("orbMaterial",{ref:r,transparent:!0,side:Bt})]})}function Us({color:s}){const e=f.useRef(null);return F(!0),U(()=>{if(!e.current)return;const a=L()?.bass??0,i=.4+a*.3;e.current.scale.setScalar(i);const n=e.current.material;n.opacity=.6+a*.4}),t.jsxs("mesh",{ref:e,children:[t.jsx("sphereGeometry",{args:[1,32,32]}),t.jsx("meshBasicMaterial",{color:s,transparent:!0,opacity:.6})]})}function Ls(){const s=f.useRef(null),e=f.useRef(0),{positions:r,sizes:a,twinklePhases:i}=f.useMemo(()=>{const u=new Float32Array(1500),l=new Float32Array(500),h=new Float32Array(500);for(let m=0;m<500;m++){const o=Math.random()*Math.PI*2,d=Math.acos(2*Math.random()-1),p=25+Math.random()*15;u[m*3]=p*Math.sin(d)*Math.cos(o),u[m*3+1]=p*Math.sin(d)*Math.sin(o),u[m*3+2]=p*Math.cos(d),l[m]=Math.random()*.5+.2,h[m]=Math.random()*Math.PI*2}return{positions:u,sizes:l,twinklePhases:h}},[]),n=f.useMemo(()=>{const c=new me;return c.setAttribute("position",new de(r,3)),c.setAttribute("size",new de(a,1)),c},[r,a]);return U((c,u)=>{if(!s.current)return;e.current+=u;const l=s.current.geometry.attributes.size;for(let h=0;h<a.length;h++){const m=Math.sin(e.current*2+i[h])*.3+.7;l.setX(h,a[h]*m)}l.needsUpdate=!0,s.current.rotation.y+=u*.01}),t.jsx("points",{ref:s,geometry:n,children:t.jsx("pointsMaterial",{size:.3,sizeAttenuation:!0,color:"#ffffff",transparent:!0,opacity:.8,blending:Z})})}const Os=f.memo(function({palette:e}){const r=f.useMemo(()=>{const a=new B(e[0]);return a.multiplyScalar(.1),a},[e]);return t.jsxs("mesh",{rotation:[-Math.PI/2,0,0],position:[0,-3,0],children:[t.jsx("planeGeometry",{args:[30,30]}),t.jsx(zt,{blur:[400,100],resolution:1024,mixBlur:1,mixStrength:.5,depthScale:1,minDepthThreshold:.85,color:r,metalness:.6,roughness:.4,mirror:.5})]})});function Vs({palette:s}){F(!0);const e=f.useMemo(()=>{const a=new B(s[0]);return a.multiplyScalar(.02),a},[s]),r=f.useMemo(()=>{const a=new B(s[0]);return a.multiplyScalar(.05),a},[s]);return t.jsxs(t.Fragment,{children:[t.jsx("color",{attach:"background",args:[e]}),t.jsx("fog",{attach:"fog",args:[r,8,30]}),t.jsx("ambientLight",{intensity:.2}),t.jsx("pointLight",{position:[10,10,10],intensity:1,color:s[0]}),t.jsx("pointLight",{position:[-10,-10,5],intensity:.8,color:s[1]||s[0]}),t.jsx("pointLight",{position:[0,5,0],intensity:.5,color:s[2]||s[0]}),t.jsx(Ls,{}),t.jsx(Us,{color:s[2]||"#ffffff"}),t.jsx(Is,{palette:s}),t.jsx(Es,{color:s[1]||"#00ffff"}),t.jsx(Fs,{color:s[0]}),!he&&t.jsx(Os,{palette:s}),t.jsx(Ds,{count:he?1e3:3e3,size:.025,color:s[0],secondaryColor:s[1]||s[0],spread:8,speed:.6,audioData:null,behavior:"orbit",opacity:.8}),t.jsx(Dt,{enableZoom:!1,enablePan:!1,autoRotate:!0,autoRotateSpeed:.3,maxPolarAngle:Math.PI/1.8,minPolarAngle:Math.PI/4}),!he&&t.jsx(ne,{enableBloom:!0,enableVignette:!0,bloomIntensity:1.2,bloomThreshold:.4,vignetteIntensity:.4})]})}function Gs({artworkUrl:s}){const[e,r]=f.useState(Ye);return f.useEffect(()=>{s?At(s,5).then(r):r(Ye)},[s]),t.jsx("div",{className:"w-full h-full",children:t.jsx(pe,{camera:{position:[0,1,7],fov:60},gl:{antialias:!he,alpha:!0,powerPreference:"high-performance"},dpr:he?[1,1]:[1,2],children:t.jsx(Vs,{palette:e})})})}ae({id:"cosmic-orb",name:"Cosmic Orb",description:"Glowing orb with album colors and reflective ground",usesMetadata:!0},Gs);const Te=W(),Xe=(s,e,r)=>{if(s<=e)return s;const a=s-e,i=r-e;return e+i*(1-Math.exp(-a/i))};function $s(){const s=f.useRef([]),e=f.useRef([]),r=f.useRef([]),a=f.useRef(0);F(!0);const i=128,n=.06,c=.015,u=i*(n+c),l=f.useMemo(()=>new Et(n,1,n),[]),h=f.useMemo(()=>Array.from({length:i},(o,d)=>{const M=.5+d/i*.4;return new Ft({color:new B().setHSL(M,.8,.5),emissive:new B().setHSL(M,1,.4),emissiveIntensity:.6,metalness:.3,roughness:.4})}),[]);U((o,d)=>{if(a.current+=d,!s.current.length)return;const p=L(),M=p?.frequencyData,R=p?.bass??0,v=p?.mid??0,b=p?.treble??0;s.current.forEach((g,x)=>{if(!g)return;let T;if(M){const k=Math.floor(M.length*.75),P=Math.floor(x/i*k);T=M[P]/255}else T=(Math.sin(a.current*3+x*.15)+1)/2;const C=.1+T*4;g.scale.y=st.lerp(g.scale.y,C,.25),g.position.y=g.scale.y/2-1;const _=g.material,w=.3+T*.7+R*.3;_.emissiveIntensity=Xe(w,.6,1.2)}),e.current.forEach((g,x)=>{if(!g)return;const T=r.current[x],C=x/3*Math.PI*2,_=.5+R*.5,w=u*.6,k=Math.sin(a.current*_+C)*w,P=Math.cos(a.current*_*.7+C)*1.5;g.position.x=k,g.position.z=-3+P,g.position.y=8+Math.sin(a.current*.3+C)*2,T&&(g.target=T,T.position.x=k,T.position.z=0,T.position.y=1);const S=[R,v,b],z=Xe(S[x],.5,.85);g.intensity=25+z*35;const A=S[x]*.1,E=[.85,.5,.75];g.color.setHSL(E[x]+A,.9,.6)})});const m=["#ff66b2","#06b6d4","#a855f7"];return t.jsxs(t.Fragment,{children:[t.jsx("color",{attach:"background",args:["#050510"]}),t.jsx("fog",{attach:"fog",args:["#050510",8,20]}),t.jsx("ambientLight",{intensity:.15}),t.jsx("pointLight",{position:[8,4,-3],intensity:.5,color:"#a855f7",distance:15}),t.jsx("pointLight",{position:[-8,4,-3],intensity:.5,color:"#06b6d4",distance:15}),m.map((o,d)=>t.jsxs("group",{children:[t.jsx("object3D",{ref:p=>{p&&(r.current[d]=p)},position:[0,1,0]}),t.jsx("spotLight",{ref:p=>{p&&(e.current[d]=p)},position:[(d-1)*3,8,-3],angle:.4,penumbra:.6,intensity:50,color:o,distance:20,decay:1.5,castShadow:!1})]},d)),t.jsxs("mesh",{rotation:[-Math.PI/2,0,0],position:[0,-1.5,0],children:[t.jsx("planeGeometry",{args:[25,25]}),t.jsx("meshStandardMaterial",{color:"#030308",metalness:.05,roughness:.95})]}),t.jsx("group",{children:Array.from({length:i},(o,d)=>t.jsx("mesh",{ref:p=>{p&&(s.current[d]=p)},geometry:l,material:h[d],position:[d*(n+c)-u/2,0,0]},d))}),!Te&&t.jsx(ne,{enableBloom:!0,enableVignette:!0,bloomIntensity:1.5,bloomThreshold:.5,bloomRadius:.6,vignetteIntensity:.4})]})}function qs(s){return t.jsx("div",{className:"w-full h-full",children:t.jsx(pe,{camera:{position:[0,2,6],fov:50},gl:{antialias:!Te,alpha:!0},dpr:Te?[1,1]:[1,2],children:t.jsx($s,{})})})}ae({id:"frequency-bars",name:"Frequency Bars",description:"Enhanced spectrum analyzer with 128 bars",usesMetadata:!1},qs);const we=W(),Qs=ke({uTexture:null,uTime:0,uSegments:12,uRotation:0,uInnerRotation:0,uTwist:0,uScale:1,uBass:0,uMid:0,uTreble:0,uIntensity:0,uChromaticAberration:0,uRadialBlur:0},`
    varying vec2 vUv;

    void main() {
      vUv = uv;
      gl_Position = projectionMatrix * modelViewMatrix * vec4(position, 1.0);
    }
  `,`
    uniform sampler2D uTexture;
    uniform float uTime;
    uniform float uSegments;
    uniform float uRotation;
    uniform float uInnerRotation;
    uniform float uTwist;
    uniform float uScale;
    uniform float uBass;
    uniform float uMid;
    uniform float uTreble;
    uniform float uIntensity;
    uniform float uChromaticAberration;
    uniform float uRadialBlur;

    varying vec2 vUv;

    #define PI 3.14159265359

    vec2 kaleidoscope(vec2 uv, float segments, float outerRot, float innerRot, float twist, float time) {
      // Convert to polar coordinates
      vec2 centered = uv - 0.5;
      float radius = length(centered);
      float angle = atan(centered.y, centered.x);

      // Apply outer rotation (whole kaleidoscope rotates)
      angle += outerRot;

      // Apply twist - inner parts rotate differently than outer parts
      // This creates the "tumbling gems" effect of a real kaleidoscope
      float twistAmount = twist * (1.0 - radius * 0.8);
      angle += twistAmount;

      // Apply inner rotation that varies by radius
      angle += innerRot * (1.0 + sin(radius * 5.0 + time) * 0.3);

      // Create kaleidoscope segments
      float segmentAngle = PI * 2.0 / segments;
      float segmentIndex = floor(angle / segmentAngle);
      angle = mod(angle, segmentAngle);

      // Mirror every other segment for kaleidoscope symmetry
      if (mod(segmentIndex, 2.0) >= 1.0) {
        angle = segmentAngle - angle;
      }

      // Add subtle wobble to each segment
      float wobble = sin(time * 2.0 + segmentIndex * 1.5) * 0.02 * (1.0 + uBass);
      angle += wobble;

      // Convert back to cartesian with slight radius distortion
      float distortedRadius = radius * (1.0 + sin(angle * 3.0 + time) * 0.05 * uMid);

      return vec2(
        cos(angle) * distortedRadius + 0.5,
        sin(angle) * distortedRadius + 0.5
      );
    }

    vec4 radialBlur(sampler2D tex, vec2 uv, float strength) {
      vec4 color = vec4(0.0);
      vec2 center = vec2(0.5);
      vec2 dir = (uv - center) * strength;

      const int samples = 8;
      float total = 0.0;

      for (int i = 0; i < samples; i++) {
        float t = float(i) / float(samples - 1);
        float weight = 1.0 - t;
        color += texture2D(tex, uv - dir * t) * weight;
        total += weight;
      }

      return color / total;
    }

    void main() {
      // Dynamic scale based on audio
      float dynamicScale = uScale * (1.0 + uBass * 0.2);

      // Apply scale from center with breathing effect
      float breathe = 1.0 + sin(uTime * 0.5) * 0.03;
      vec2 scaledUv = (vUv - 0.5) / (dynamicScale * breathe) + 0.5;

      // Apply kaleidoscope transformation with all rotations
      vec2 kUv = kaleidoscope(scaledUv, uSegments, uRotation, uInnerRotation, uTwist, uTime);

      // Chromatic aberration that shifts with audio
      float chromaOffset = uChromaticAberration * (1.0 + uTreble * 2.0);
      vec2 chromaDir = normalize(kUv - 0.5) * chromaOffset;

      vec4 color;

      if (uRadialBlur > 0.001) {
        float blurStrength = uRadialBlur * uBass * 0.08;

        vec4 rChannel = radialBlur(uTexture, kUv + chromaDir, blurStrength);
        vec4 gChannel = radialBlur(uTexture, kUv, blurStrength);
        vec4 bChannel = radialBlur(uTexture, kUv - chromaDir, blurStrength);

        color = vec4(rChannel.r, gChannel.g, bChannel.b, 1.0);
      } else {
        float r = texture2D(uTexture, kUv + chromaDir).r;
        float g = texture2D(uTexture, kUv).g;
        float b = texture2D(uTexture, kUv - chromaDir).b;

        color = vec4(r, g, b, 1.0);
      }

      // Enhance colors based on audio (reduced to prevent blowout)
      color.rgb *= 0.85 + uIntensity * 0.15;

      // Add subtle shimmer effect
      float shimmer = sin(kUv.x * 20.0 + uTime * 3.0) * sin(kUv.y * 20.0 - uTime * 2.0);
      color.rgb += shimmer * 0.015 * uTreble;

      // Radial rainbow tint (subtle)
      float dist = length(vUv - 0.5) * 2.0;
      vec3 rainbow = vec3(
        sin(dist * 3.0 + uTime) * 0.5 + 0.5,
        sin(dist * 3.0 + uTime + 2.094) * 0.5 + 0.5,
        sin(dist * 3.0 + uTime + 4.189) * 0.5 + 0.5
      );
      color.rgb = mix(color.rgb, color.rgb * rainbow, 0.08 * uMid);

      // Edge glow (subtle, only at edges)
      float edgeGlow = smoothstep(0.7, 1.0, dist) * (0.1 + uBass * 0.15);
      color.rgb += vec3(0.4, 0.2, 0.6) * edgeGlow;

      gl_FragColor = color;
    }
  `);Pe({KaleidoscopeMaterial:Qs});function lt({segments:s}){const e=f.useRef(null);F(!0);const r=f.useRef(0),a=300,{positions:i,velocities:n,phases:c,lifetimes:u,segmentIndices:l}=f.useMemo(()=>{const d=new Float32Array(a*3),p=new Float32Array(a*3),M=new Float32Array(a),R=new Float32Array(a),v=new Float32Array(a);for(let b=0;b<a;b++)M[b]=Math.random()*Math.PI*2,v[b]=Math.floor(Math.random()*s),R[b]=0;return{positions:d,velocities:p,phases:M,lifetimes:R,segmentIndices:v}},[s]),h=f.useMemo(()=>new Ne,[]),m=f.useMemo(()=>new B,[]),o=f.useRef(0);return U((d,p)=>{if(!e.current)return;r.current+=p;const M=r.current,v=L()?.bass??0;if(v>.3&&Math.random()<v*.5){const b=Math.floor(v*5)+1;for(let g=0;g<b;g++){const x=o.current%a,C=l[x]/s*Math.PI*2,_=Math.random()*2.5+.5,w=Math.cos(C)*_,k=Math.sin(C)*_;i[x*3]=w,i[x*3+1]=k,i[x*3+2]=.1;const P=.5+Math.random()*1.5;n[x*3]=w*P*.3+(Math.random()-.5)*.5,n[x*3+1]=k*P*.3+(Math.random()-.5)*.5,n[x*3+2]=(Math.random()-.5)*.2,u[x]=1,o.current++}}for(let b=0;b<a;b++){if(u[b]<=0){h.position.set(0,0,-10),h.scale.setScalar(.001),h.updateMatrix(),e.current.setMatrixAt(b,h.matrix);continue}const g=b*3;i[g]+=n[g]*p,i[g+1]+=n[g+1]*p,i[g+2]+=n[g+2]*p,u[b]-=p*2;const x=Math.sin(M*10+c[b])*.5+.5,T=u[b]*.04*(.5+x*.5);h.position.set(i[g],i[g+1],i[g+2]),h.scale.setScalar(Math.max(.001,T)),h.updateMatrix(),e.current.setMatrixAt(b,h.matrix);const C=(l[b]/s+M*.1)%1;m.setHSL(C,.8,.4+u[b]*.2),e.current.setColorAt(b,m)}e.current.instanceMatrix.needsUpdate=!0,e.current.instanceColor&&(e.current.instanceColor.needsUpdate=!0)}),t.jsxs("instancedMesh",{ref:e,args:[void 0,void 0,a],children:[t.jsx("circleGeometry",{args:[1,8]}),t.jsx("meshBasicMaterial",{transparent:!0,opacity:.9,toneMapped:!1,blending:Z,depthWrite:!1})]})}function Hs(){const s=f.useRef(null);F(!0);const e=f.useRef(0);return U((r,a)=>{if(!s.current)return;e.current+=a;const n=L()?.bass??0;s.current.rotation.z=e.current*.1;const c=2.8+n*.2;s.current.scale.setScalar(c);const u=s.current.material;u.opacity=.15+n*.15}),t.jsxs("mesh",{ref:s,position:[0,0,-.1],children:[t.jsx("ringGeometry",{args:[.95,1,64]}),t.jsx("meshBasicMaterial",{color:"#8b5cf6",transparent:!0,opacity:.4,toneMapped:!1,blending:Z})]})}function Ys({texture:s}){const e=f.useRef(null);F(!0);const r=f.useRef(0),a=f.useRef(0),i=f.useRef(0),n=f.useRef(0);return U((c,u)=>{if(!e.current)return;r.current+=u;const l=L(),h=l?.bass??0,m=l?.mid??0,o=l?.treble??0,d=(l?.averageFrequency??0)/255;a.current+=.002+h*.008,i.current-=.004+m*.01;const p=Math.sin(r.current*.3)*.2+o*.3;n.current+=(p-n.current)*.03,e.current.uniforms.uTime.value=r.current,e.current.uniforms.uRotation.value=a.current,e.current.uniforms.uInnerRotation.value=i.current,e.current.uniforms.uTwist.value=n.current,e.current.uniforms.uScale.value=1+o*.1,e.current.uniforms.uBass.value=h,e.current.uniforms.uMid.value=m,e.current.uniforms.uTreble.value=o,e.current.uniforms.uIntensity.value=d,e.current.uniforms.uChromaticAberration.value=.003,e.current.uniforms.uRadialBlur.value=1}),t.jsxs("mesh",{position:[0,0,0],children:[t.jsx("planeGeometry",{args:[6,6]}),t.jsx("kaleidoscopeMaterial",{ref:e,uTexture:s,uSegments:8,uChromaticAberration:.003,uRadialBlur:1})]})}function Xs({artworkUrl:s}){F(!0);const e=Ut(Lt,s);return f.useMemo(()=>{e.wrapS=Le,e.wrapT=Le,e.minFilter=ye,e.magFilter=ye},[e]),t.jsxs(t.Fragment,{children:[t.jsx("color",{attach:"background",args:["#050010"]}),t.jsx(Ys,{texture:e}),t.jsx(Hs,{}),t.jsx(lt,{segments:12}),!we&&t.jsx(ne,{enableBloom:!0,enableVignette:!0,bloomIntensity:.6,bloomThreshold:.7,vignetteIntensity:.4})]})}function Ws(){const s=f.useRef(null),e=f.useRef(null);F(!0);const r=f.useRef(0);return U((a,i)=>{if(!s.current)return;r.current+=i;const n=L(),c=n?.bass??0,u=n?.mid??0;s.current.rotation.z+=.01+c*.02,s.current.rotation.x=Math.sin(r.current*.5)*.2,s.current.rotation.y=Math.cos(r.current*.3)*.2;const l=1+c*.3;s.current.scale.setScalar(l),e.current&&(e.current.rotation.z=-r.current*.2,e.current.scale.setScalar(2.5+u*.3))}),t.jsxs(t.Fragment,{children:[t.jsx("color",{attach:"background",args:["#050010"]}),t.jsxs("mesh",{ref:s,children:[t.jsx("icosahedronGeometry",{args:[1.5,2]}),t.jsx("meshBasicMaterial",{color:"#8b5cf6",wireframe:!0,toneMapped:!1})]}),t.jsxs("mesh",{ref:e,position:[0,0,-.5],children:[t.jsx("torusGeometry",{args:[1,.02,16,100]}),t.jsx("meshBasicMaterial",{color:"#06b6d4",toneMapped:!1,blending:Z})]}),t.jsx(lt,{segments:12}),!we&&t.jsx(ne,{enableBloom:!0,enableVignette:!0,bloomIntensity:1.2,bloomThreshold:.5,vignetteIntensity:.5})]})}function Ks({artworkUrl:s}){const[e,r]=f.useState(null);return f.useEffect(()=>{if(!s){r(null);return}let a=null,i=!1;if(It())fetch(s).then(n=>n.blob()).then(n=>{i||(a=URL.createObjectURL(n),r(a))}).catch(()=>{i||r(null)});else{const n=new Image;n.onload=()=>{i||r(s)},n.onerror=()=>{i||r(null)},n.src=s}return()=>{i=!0,a&&URL.revokeObjectURL(a)}},[s]),t.jsx("div",{className:"w-full h-full",children:t.jsx(pe,{camera:{position:[0,0,5],fov:50},gl:{antialias:!we,alpha:!0,powerPreference:"high-performance"},dpr:we?[1,1]:[1,2],children:e?t.jsx(Xs,{artworkUrl:e}):t.jsx(Ws,{})})})}ae({id:"album-kaleidoscope",name:"Album Kaleidoscope",description:"Shader-based kaleidoscope with RGB split",usesMetadata:!0},Ks);const Se=W();let We=0;function Zs(){const s=f.useRef(null),e=f.useRef(null);F(!0);const r=3e3,a=f.useMemo(()=>{const c=[];for(let u=0;u<r;u++){const l=Math.random()*100,h=20+Math.random()*100,m=.01+Math.random()/200,o=-30+Math.random()*60,d=-30+Math.random()*60,p=-30+Math.random()*60;c.push({t:l,factor:h,speed:m,xFactor:o,yFactor:d,zFactor:p,mx:0,my:0})}return c},[]),i=f.useMemo(()=>new Ne,[]),n=f.useMemo(()=>new B,[]);return U(c=>{if(!s.current)return;const u=L(),l=u?.bass??0,h=u?.mid??0,m=u?.treble??0;e.current&&(e.current.position.set(Math.sin(c.clock.elapsedTime)*5*(1+l),Math.cos(c.clock.elapsedTime*.7)*5*(1+h),Math.sin(c.clock.elapsedTime*.5)*3),e.current.intensity=3+l*5),a.forEach((o,d)=>{const{factor:p,speed:M,xFactor:R,yFactor:v,zFactor:b}=o,g=o.t+=M*(.5+l*2),x=Math.cos(g)+Math.sin(g*1)/10,T=Math.sin(g)+Math.cos(g*2)/10,C=Math.cos(g)*.5+.5,_=l*2;i.position.set(R+Math.cos(g/10*p)+Math.sin(g*1)*p/10+x*_,v+Math.sin(g/10*p)+Math.cos(g*2)*p/10+T*_,b+Math.cos(g/10*p)+Math.sin(g*3)*p/10);const w=15-i.position.z,k=w<8?w/8:1;i.scale.setScalar(C*.3*(1+m*.5)*k),i.rotation.set(C*5,C*5,C*5),i.updateMatrix(),s.current.setMatrixAt(d,i.matrix);const P=(.7+C*.2+h*.1)%1;n.setHSL(P,.8,.3+l*.2),s.current.setColorAt(d,n)}),s.current.instanceMatrix.needsUpdate=!0,s.current.instanceColor&&(s.current.instanceColor.needsUpdate=!0)}),t.jsxs(t.Fragment,{children:[t.jsx("pointLight",{ref:e,distance:60,intensity:5,color:"#8b5cf6"}),t.jsxs("instancedMesh",{ref:s,args:[void 0,void 0,r],children:[t.jsx("dodecahedronGeometry",{args:[1,0]}),t.jsx("meshStandardMaterial",{color:"#1a0030",emissive:"#1a0030",emissiveIntensity:.3,roughness:.5,toneMapped:!1})]})]})}function Js({words:s,currentLineWords:e}){const r=f.useRef(null);F(!0);const[a,i]=f.useState([]),n=f.useRef([]),c=f.useRef([]),{viewport:u}=_e(),l=f.useRef(0),h=f.useRef(0);U((o,d)=>{if(!r.current)return;l.current+=d;const p=L(),M=p?.bass??0,R=p?.mid??0,v=p?.treble??0,b=e.join(" "),g=c.current.join(" ");if(b!==g&&e.length>0&&(c.current=[...e],e.forEach((x,T)=>{const C=T/e.length*Math.PI*2,_=1+Math.random()*2;n.current.push({id:++We,text:x,position:new I(0,0,0),velocity:new I(Math.cos(C)*_,Math.sin(C)*_,(Math.random()-.5)*.5),rotation:new Oe(Math.random()*Math.PI,Math.random()*Math.PI,Math.random()*Math.PI),rotationSpeed:new I((Math.random()-.5)*.5,(Math.random()-.5)*.5,(Math.random()-.5)*.5),scale:.3+Math.random()*.2,opacity:1,hue:.75+Math.random()*.1,life:0,maxLife:4+Math.random()*2,isCurrentLine:!0,shimmerPhase:0})})),Math.random()<.12+M*.2&&s.length>0){const x=s[Math.floor(Math.random()*s.length)],T=Math.floor(Math.random()*4),C=u.width/2+2,_=u.height/2+2;let w,k,P,S;switch(T){case 0:w=(Math.random()-.5)*C*2,k=-_-1,P=(Math.random()-.5)*.3,S=.3+Math.random()*.5;break;case 1:w=C+1,k=(Math.random()-.5)*_*2,P=-(.3+Math.random()*.5),S=(Math.random()-.5)*.3;break;case 2:w=(Math.random()-.5)*C*2,k=_+1,P=(Math.random()-.5)*.3,S=-(.3+Math.random()*.5);break;default:w=-C-1,k=(Math.random()-.5)*_*2,P=.3+Math.random()*.5,S=(Math.random()-.5)*.3}n.current.push({id:++We,text:x,position:new I(w,k,-8+Math.random()*2),velocity:new I(P*.7,S*.7,0),rotation:new Oe(Math.random()*.3,Math.random()*.3,0),rotationSpeed:new I((Math.random()-.5)*.05,(Math.random()-.5)*.05,(Math.random()-.5)*.05),scale:.15+Math.random()*.1,opacity:.35,hue:.55+Math.random()*.2,life:0,maxLife:10+Math.random()*5,isCurrentLine:!1,shimmerPhase:Math.random()*Math.PI*2})}n.current=n.current.filter(x=>{x.life+=d,x.position.add(x.velocity.clone().multiplyScalar(d*(1+M*2))),x.rotation.x+=x.rotationSpeed.x*d*(1+R),x.rotation.y+=x.rotationSpeed.y*d*(1+R),x.rotation.z+=x.rotationSpeed.z*d*(1+v);const T=x.life/x.maxLife,C=.6,_=T>C?(T-C)/(1-C):0;return x.opacity=x.isCurrentLine?Math.max(0,1-_):Math.max(0,.35-_*.35),x.life<x.maxLife}),h.current++,h.current%10===0&&i(n.current.map(x=>({...x})))});const m=o=>{if(o.isCurrentLine)return 0;const d=Math.sin(l.current*2+o.shimmerPhase)*.5+.5;return d>.85?(d-.85)*4:0};return t.jsx("group",{ref:r,children:a.map(o=>{const d=m(o);return t.jsx(Ot,{position:[o.position.x,o.position.y,o.position.z],rotation:[o.rotation.x,o.rotation.y,o.rotation.z],fontSize:o.scale*(o.isCurrentLine?1.5:.8),color:new B().setHSL(o.hue,o.isCurrentLine?.85:.5+d*.3,o.isCurrentLine?.7:.4+d*.4),anchorX:"center",anchorY:"middle",font:"https://cdn.jsdelivr.net/fontsource/fonts/inter@latest/latin-700-normal.woff",fillOpacity:o.opacity+(o.isCurrentLine?0:d*.3),children:o.text},o.id)})})}function er(){const s=f.useRef(null);return F(!0),U(()=>{if(!s.current)return;const r=L()?.bass??0,a=s.current.material;a.opacity=.95+r*.05}),t.jsxs("mesh",{ref:s,position:[0,0,-20],children:[t.jsx("planeGeometry",{args:[200,200]}),t.jsx("meshBasicMaterial",{color:"#050010",transparent:!0,opacity:.95})]})}function tr({allWords:s,currentLineWords:e}){return F(!0),t.jsxs(t.Fragment,{children:[t.jsx("color",{attach:"background",args:["#030008"]}),t.jsx("fog",{attach:"fog",args:["#050010",20,80]}),t.jsx("ambientLight",{intensity:.1}),t.jsx("pointLight",{position:[10,10,10],intensity:1,color:"#8b5cf6"}),t.jsx("pointLight",{position:[-10,-10,5],intensity:.5,color:"#06b6d4"}),t.jsx("pointLight",{position:[0,0,10],intensity:.4,color:"#c4b5fd",distance:25}),t.jsx(er,{}),t.jsx(Zs,{}),t.jsx(Js,{words:s,currentLineWords:e}),!Se&&t.jsx(ne,{enableBloom:!0,enableVignette:!0,bloomIntensity:1.5,bloomThreshold:.3,vignetteIntensity:.4})]})}function sr({currentLine:s,nextLine:e}){const r=f.useRef(null);return f.useEffect(()=>{const a=r.current;if(!a)return;const i=a.getContext("2d");if(!i)return;let n;const c=()=>{a.width=a.clientWidth*window.devicePixelRatio,a.height=a.clientHeight*window.devicePixelRatio};c(),window.addEventListener("resize",c);const u=()=>{const l=a.width,h=a.height,m=window.devicePixelRatio;i.clearRect(0,0,l,h);const o=L(),d=o?.bass??0,p=(o?.averageFrequency??0)/255;if(i.save(),i.textAlign="center",i.textBaseline="middle",s){const M=(48+d*16)*m;i.font=`bold ${M}px system-ui, -apple-system, sans-serif`,i.shadowColor="hsla(280, 100%, 60%, 0.9)",i.shadowBlur=(30+p*40)*m,i.fillStyle=`hsla(280, 80%, ${70+p*20}%, 0.95)`,i.fillText(s,l/2,h*.4),i.shadowBlur=(50+d*30)*m,i.fillText(s,l/2,h*.4)}if(e){const M=(28+d*8)*m;i.font=`${M}px system-ui, -apple-system, sans-serif`,i.shadowColor="hsla(185, 100%, 50%, 0.6)",i.shadowBlur=(15+p*15)*m,i.fillStyle="hsla(185, 70%, 55%, 0.7)",i.fillText(e,l/2,h*.58)}i.restore(),n=requestAnimationFrame(u)};return u(),()=>{cancelAnimationFrame(n),window.removeEventListener("resize",c)}},[s,e]),t.jsx("canvas",{ref:r,className:"absolute inset-0 w-full h-full pointer-events-none",style:{zIndex:10}})}function rr({lyrics:s,track:e}){F(!0);const r=Y(u=>u.currentTime),a=f.useMemo(()=>{if(!s||s.length===0)return`${e?.title||""} ${e?.artist||""}`.split(/\s+/).filter(h=>h.length>0);const u=[];return s.forEach(l=>{l.text.split(/\s+/).forEach(h=>{const m=h.replace(/[^\w']/g,"");m.length>1&&u.push(m)})}),[...new Set(u)]},[s,e]),{currentLine:i,currentLineWords:n,nextLine:c}=f.useMemo(()=>{if(!s||s.length===0)return{currentLine:"",currentLineWords:[],nextLine:""};let u=-1;for(let o=s.length-1;o>=0;o--)if(s[o].time<=r){u=o;break}if(u<0)return{currentLine:"",currentLineWords:[],nextLine:""};const l=s[u].text,h=l.split(/\s+/).map(o=>o.replace(/[^\w']/g,"")).filter(o=>o.length>0),m=u<s.length-1?s[u+1].text:"";return{currentLine:l,currentLineWords:h,nextLine:m}},[s,r]);return t.jsxs("div",{className:"relative w-full h-full",children:[t.jsx(pe,{camera:{position:[0,0,15],fov:50},gl:{antialias:!Se,alpha:!0,powerPreference:"high-performance"},dpr:Se?[1,1]:[1,2],children:t.jsx(tr,{allWords:a,currentLineWords:n})}),t.jsx(sr,{currentLine:i,nextLine:c})]})}ae({id:"lyrics",name:"Lyrics",description:"Karaoke-style lyrics with next-line preview",usesMetadata:!0},rr);const ct=W(),V=60,Re=30;function ar(s){const e=2+Math.random()*Math.random()*6;return{x:Math.random()*s,y:-e*2,radius:e,velocityY:.15+Math.random()*.35,velocityX:(Math.random()-.5)*.15,trail:[],opacity:.4+Math.random()*.4,stuck:!1,mass:0,releaseThreshold:.3+Math.random()*.7}}function ir(s,e,r){return s.stuck?(s.velocityY=0,s.velocityX=(Math.random()-.5)*.02,s.mass+=.01,s.mass>s.releaseThreshold&&(s.stuck=!1,s.velocityY=.3+s.mass*.8,s.mass=0,r.push({x:s.x,y:s.y,radius:s.radius*(.3+Math.random()*.3),opacity:.3+Math.random()*.2}))):(s.velocityY+=.008,s.velocityY=Math.min(s.velocityY,1.5),s.velocityX*=.995,Math.random()<.02&&(s.velocityY*=.4+Math.random()*.3),s.velocityY<.25&&Math.random()<.05&&(s.stuck=!0,s.mass=0,s.releaseThreshold=.3+Math.random()*.7),Math.random()<.03&&r.push({x:s.x,y:s.y,radius:s.radius*(.3+Math.random()*.3),opacity:.3+Math.random()*.2})),s.trail.push({x:s.x,y:s.y,age:0}),s.trail=s.trail.map(a=>({...a,age:a.age+1})).filter(a=>a.age<Re),s.x+=s.velocityX,s.y+=s.velocityY,s.y<e+s.radius*2}function nr(s,e,r){return{x:Math.random()*s,y:Math.random()*e,radius:30+Math.random()*80,color:r[Math.floor(Math.random()*r.length)],velocityX:(Math.random()-.5)*.2,velocityY:(Math.random()-.5)*.2,phase:Math.random()*Math.PI*2,brightness:.3+Math.random()*.4}}function or(s,e,r,a){s.x+=s.velocityX,s.y+=s.velocityY,s.brightness=.3+Math.sin(a*.5+s.phase)*.15,s.x<-s.radius&&(s.x=e+s.radius),s.x>e+s.radius&&(s.x=-s.radius),s.y<-s.radius&&(s.y=r+s.radius),s.y>r+s.radius&&(s.y=-s.radius)}const lr=`
  varying vec2 vUv;
  void main() {
    vUv = uv;
    gl_Position = projectionMatrix * modelViewMatrix * vec4(position, 1.0);
  }
`,cr=`
  uniform vec2 uBokehPos[12];
  uniform vec3 uBokehColor[12];
  uniform float uBokehRadius[12];
  uniform float uBokehBrightness[12];
  uniform vec2 uResolution;

  varying vec2 vUv;

  void main() {
    // Dark night gradient
    vec3 color = mix(
      vec3(0.039, 0.063, 0.125),
      vec3(0.031, 0.063, 0.094),
      vUv.y
    );
    // Slightly lighter mid-band
    float midBand = smoothstep(0.0, 0.5, vUv.y) * smoothstep(1.0, 0.5, vUv.y);
    color = mix(color, vec3(0.051, 0.082, 0.145), midBand * 0.5);

    vec2 fragCoord = vUv * uResolution;

    for (int i = 0; i < 12; i++) {
      vec2 diff = fragCoord - uBokehPos[i];
      float dist = length(diff);
      float r = uBokehRadius[i];
      if (dist > r * 2.0) continue;

      // Soft radial falloff
      float falloff = smoothstep(r, r * 0.1, dist);
      color += uBokehColor[i] * falloff * uBokehBrightness[i] * 0.6;

      // Soft outer glow
      float outerGlow = smoothstep(r * 2.0, r, dist);
      color += uBokehColor[i] * outerGlow * uBokehBrightness[i] * 0.15;
    }

    // Dim for out-of-focus glass effect
    color *= 0.85;

    gl_FragColor = vec4(color, 1.0);
  }
`,ur=`
  varying vec2 vUv;
  void main() {
    vUv = uv;
    gl_Position = projectionMatrix * modelViewMatrix * vec4(position, 1.0);
  }
`,fr=`
  uniform sampler2D tBackground;
  uniform vec4 uDroplets[${V}];
  uniform vec3 uDropletDir[${V}];
  uniform int uDropletCount;
  uniform vec2 uResolution;
  uniform float uTime;
  uniform float uBass;

  varying vec2 vUv;

  void main() {
    vec3 color = texture2D(tBackground, vUv).rgb;
    vec2 fragCoord = vUv * uResolution;

    for (int i = 0; i < ${V}; i++) {
      if (i >= uDropletCount) break;

      vec2 center = uDroplets[i].xy;
      float radius = uDroplets[i].z;
      float opacity = uDroplets[i].w;

      vec2 dir = uDropletDir[i].xy;
      float stretch = uDropletDir[i].z;
      float halfLen = radius * stretch;

      vec2 diff = fragCoord - center;
      float maxDist = radius * 1.5 + halfLen;

      // Early rejection (squared distance avoids sqrt for far pixels)
      float distSq = dot(diff, diff);
      if (distSq > maxDist * maxDist) continue;

      // Project onto capsule axis
      float along = dot(diff, dir);
      float clampedAlong = clamp(along, -halfLen, halfLen);

      // t: 0 at trailing end, 1 at leading end (epsilon avoids div-by-zero)
      float t = (clampedAlong + halfLen + 0.001) / (2.0 * halfLen + 0.002);

      // Taper radius: full at leading end, 35% at trailing end
      float taperRadius = radius * mix(0.35, 1.0, t);
      // Branchless stationary fallback — pure circle when stretch ≈ 0
      taperRadius = mix(radius, taperRadius, step(0.01, stretch));

      // Nearest point on capsule centerline
      vec2 nearest = center + dir * clampedAlong;
      float capsuleDist = length(fragCoord - nearest);
      float nd = capsuleDist / taperRadius;

      // Edge softness — antialiased boundary
      float edge = smoothstep(1.0, 0.85, nd);
      if (edge < 0.001) continue;

      // --- Refraction: offset UV toward nearest capsule point ---
      vec2 refractDir = capsuleDist > 0.001
        ? (nearest - fragCoord) / capsuleDist
        : vec2(0.0);
      float refractStrength = (1.0 - nd * nd) * 0.03 * radius;
      vec2 refractedUv = vUv + refractDir * refractStrength / uResolution;

      // --- Chromatic aberration: sample RGB at offset UVs ---
      vec2 chromaOffset = refractDir * refractStrength * 0.4 * nd / uResolution;
      float r = texture2D(tBackground, refractedUv + chromaOffset).r;
      float g = texture2D(tBackground, refractedUv).g;
      float b = texture2D(tBackground, refractedUv - chromaOffset).b;
      vec3 refractedColor = vec3(r, g, b);

      // --- Subsurface scattering: brighten center ---
      float sss = smoothstep(1.0, 0.0, nd);
      sss = sss * sss;
      refractedColor *= 1.0 + sss * 0.5;

      // --- Caustic: bright spot near leading edge ---
      vec2 frontPt = center + dir * halfLen;
      vec2 causticCenter = frontPt + vec2(-radius * 0.2, -radius * 0.3);
      float causticDist = length(fragCoord - causticCenter) / radius;
      float caustic = exp(-causticDist * causticDist * 3.0) * 0.4;
      refractedColor += vec3(caustic);

      // --- Fresnel rim: edges reflect more ---
      float fresnel = pow(nd, 3.0) * 0.5;
      refractedColor = mix(refractedColor, vec3(0.7, 0.85, 1.0), fresnel);

      // --- Specular highlight: near leading edge ---
      vec2 specCenter = frontPt + vec2(-radius * 0.3, -radius * 0.3);
      float specDist = length(fragCoord - specCenter) / radius;
      float specular = exp(-specDist * specDist * 8.0) * 0.7;
      refractedColor += vec3(specular);

      // Blend with edge softness and opacity
      color = mix(color, refractedColor, edge * opacity);
    }

    gl_FragColor = vec4(color, 1.0);
  }
`,hr=ke({tBackground:null,uDroplets:Array.from({length:V},()=>new at),uDropletDir:Array.from({length:V},()=>new I),uDropletCount:0,uResolution:new G,uTime:0,uBass:0},ur,fr);Pe({CompositorMaterial:hr});function dr(s){const e=s.replace("#","");return[parseInt(e.substring(0,2),16)/255,parseInt(e.substring(2,4),16)/255,parseInt(e.substring(4,6),16)/255]}function mr({palette:s}){const{gl:e,size:r}=_e();F(!0);const a=f.useRef([]),i=f.useRef([]),n=f.useRef([]),c=f.useRef(0),u=f.useRef(0),l=f.useRef(null),h=f.useMemo(()=>Array.from({length:V},()=>new at),[]),m=f.useMemo(()=>Array.from({length:V},()=>new I),[]),o=f.useMemo(()=>new fe(Math.max(1,Math.floor(r.width/2)),Math.max(1,Math.floor(r.height/2)),{minFilter:ye,magFilter:ye}),[]),d=f.useMemo(()=>{const p=new Gt,M=new tt(-1,1,1,-1,.1,100);M.position.z=1;const R=new K({uniforms:{uBokehPos:{value:Array.from({length:12},()=>new G)},uBokehColor:{value:Array.from({length:12},()=>new I(1,1,1))},uBokehRadius:{value:new Float32Array(12).fill(50)},uBokehBrightness:{value:new Float32Array(12).fill(.3)},uResolution:{value:new G(1,1)}},vertexShader:lr,fragmentShader:cr,depthTest:!1,depthWrite:!1}),v=new et(new $t(2,2),R);p.add(v);const b=new Float32Array(V*Re*2*3),g=new me;g.setAttribute("position",new de(b,3)),g.setDrawRange(0,0);const x=new ze({color:13163775,transparent:!0,opacity:.15,blending:Z,depthTest:!1,depthWrite:!1}),T=new qt(g,x);return p.add(T),{scene:p,camera:M,bokehMaterial:R,trailPositions:b,trailGeometry:g}},[]);return f.useEffect(()=>{n.current=Array.from({length:12},()=>nr(r.width,r.height,s))},[s,r.width,r.height]),f.useEffect(()=>{o.setSize(Math.max(1,Math.floor(r.width/2)),Math.max(1,Math.floor(r.height/2))),d.bokehMaterial.uniforms.uResolution.value.set(r.width,r.height)},[r.width,r.height,o,d.bokehMaterial]),f.useEffect(()=>()=>{o.dispose(),d.bokehMaterial.dispose(),d.trailGeometry.dispose()},[o,d]),U(()=>{const p=r.width,M=r.height;if(p===0||M===0)return;const v=L()?.bass??0;u.current+=(v-u.current)*.03;const b=u.current;c.current+=.016;const g=d.bokehMaterial.uniforms.uBokehPos.value,x=d.bokehMaterial.uniforms.uBokehColor.value,T=d.bokehMaterial.uniforms.uBokehRadius.value,C=d.bokehMaterial.uniforms.uBokehBrightness.value;n.current.forEach((y,N)=>{or(y,p,M,c.current),g[N].set(y.x,M-y.y);const[D,O,ee]=dr(y.color);x[N].set(D,O,ee),T[N]=y.radius,C[N]=y.brightness+b*.2});const _=d.trailPositions;let w=0;const k=V*Re*2;for(const y of a.current)if(!(y.trail.length<2)){for(let N=0;N<y.trail.length-1&&!(w>=k);N++){const D=y.trail[N],O=y.trail[N+1],ee=D.x/p*2-1,te=1-D.y/M*2,X=O.x/p*2-1,je=1-O.y/M*2,q=w*3;_[q]=ee,_[q+1]=te,_[q+2]=0,_[q+3]=X,_[q+4]=je,_[q+5]=0,w+=2}if(w>=k)break}d.trailGeometry.attributes.position.needsUpdate=!0,d.trailGeometry.setDrawRange(0,w),e.setRenderTarget(o),e.render(d.scene,d.camera),e.setRenderTarget(null);const P=.02+b*.02;Math.random()<P&&a.current.push(ar(p));const S=i.current;a.current=a.current.filter(y=>ir(y,M,S)),a.current.length>V&&(a.current=a.current.slice(-V));for(let y=S.length-1;y>=0;y--)S[y].opacity-=.001,S[y].opacity<.05&&S.splice(y,1);S.length>120&&S.splice(0,S.length-120);const z=Math.min(a.current.length,V);for(let y=0;y<z;y++){const N=a.current[y];h[y].set(N.x,M-N.y,N.radius,N.opacity);const D=Math.sqrt(N.velocityX*N.velocityX+N.velocityY*N.velocityY);D>.001?m[y].set(N.velocityX/D,-N.velocityY/D,Math.min(D*3,4)):m[y].set(0,-1,0)}const A=V-z,E=Math.max(0,S.length-A),Q=Math.min(S.length,A);for(let y=0;y<Q;y++){const N=S[E+y];h[z+y].set(N.x,M-N.y,N.radius,N.opacity),m[z+y].set(0,-1,0)}const J=z+Q;for(let y=J;y<V;y++)h[y].set(0,0,0,0),m[y].set(0,0,0);const $=l.current;$&&($.uniforms.tBackground.value=o.texture,$.uniforms.uDroplets.value=h,$.uniforms.uDropletDir.value=m,$.uniforms.uDropletCount.value=J,$.uniforms.uResolution.value.set(p,M),$.uniforms.uTime.value=c.current,$.uniforms.uBass.value=b)}),t.jsxs(t.Fragment,{children:[t.jsxs("mesh",{children:[t.jsx("planeGeometry",{args:[5,5]}),t.jsx("compositorMaterial",{ref:l})]}),!ct&&t.jsx(ne,{enableBloom:!0,enableVignette:!0,bloomIntensity:.8,bloomThreshold:.6,vignetteIntensity:.4})]})}function pr({artworkUrl:s}){const e=Vt(s);return t.jsx("div",{className:"w-full h-full bg-[#0a1020]",children:t.jsx(pe,{camera:{position:[0,0,1],fov:90},dpr:ct?[1,1]:[1,2],gl:{antialias:!1,powerPreference:"high-performance"},children:t.jsx(mr,{palette:e})})})}ae({id:"rain-window",name:"Rain Window",description:"Peaceful rain on glass with soft bokeh lights",usesMetadata:!0},pr);function gr(s){const e=Math.floor(s/60),r=s%60;return`${e}:${r.toString().padStart(2,"0")}`}function xr({track:s,isPlaying:e}){const r=f.useRef(null),[a,i]=f.useState(!1),n=gt(),c=Y(g=>g.currentTime),u=s?.id??null,{data:l,isLoading:h}=Fe({queryKey:["video-status",u],queryFn:()=>oe.getStatus(u),enabled:!!u,refetchInterval:g=>{const x=g.state.data?.download_status;return x==="downloading"||x==="pending"?1e3:!1}}),{data:m,isLoading:o,isError:d,refetch:p}=Fe({queryKey:["video-search",u],queryFn:()=>oe.search(u),enabled:!1}),M=Ie({mutationFn:({videoUrl:g})=>oe.download(u,g),onSuccess:()=>{n.invalidateQueries({queryKey:["video-status",u]}),i(!1)}}),R=Ie({mutationFn:()=>oe.delete(u),onSuccess:()=>{n.invalidateQueries({queryKey:["video-status",u]})}});f.useEffect(()=>{if(r.current&&l?.has_video){const g=r.current;Math.abs(g.currentTime-c)>.5&&(g.currentTime=c),e&&g.paused?g.play().catch(()=>{}):!e&&!g.paused&&g.pause()}},[c,e,l?.has_video]),f.useEffect(()=>{i(!1)},[u]);const v=()=>{i(!0),p()},b=g=>{M.mutate({videoUrl:g.url})};return u?h?t.jsx("div",{className:"w-full h-full flex items-center justify-center bg-zinc-900",children:t.jsx(ue,{className:"w-8 h-8 animate-spin text-zinc-400"})}):l?.has_video?t.jsxs("div",{className:"w-full h-full bg-black relative",children:[t.jsx("video",{ref:r,src:oe.getStreamUrl(u),className:"w-full h-full object-contain",muted:!0,playsInline:!0}),t.jsx("button",{onClick:()=>R.mutate(),className:"absolute top-4 right-4 p-2 bg-black/50 hover:bg-red-500/50 rounded-full transition-colors",title:"Delete video",children:t.jsx(ss,{className:"w-5 h-5"})})]}):a?t.jsx("div",{className:"w-full h-full bg-zinc-900 overflow-auto p-4 sm:p-6",children:t.jsxs("div",{className:"max-w-2xl mx-auto",children:[t.jsx("h3",{className:"text-xl font-bold mb-4",children:"Select a music video"}),o?t.jsx("div",{className:"flex items-center justify-center py-12",children:t.jsx(ue,{className:"w-8 h-8 animate-spin text-zinc-400"})}):d?t.jsxs("div",{className:"flex flex-col items-center py-12",children:[t.jsx(ce,{className:"w-12 h-12 text-red-500 mb-3 opacity-50"}),t.jsx("p",{className:"text-red-400",children:"Search failed"}),t.jsx("button",{onClick:()=>p(),className:"mt-4 px-4 py-2 bg-zinc-800 hover:bg-zinc-700 rounded-lg transition-colors text-zinc-300",children:"Try again"})]}):m&&m.length>0?t.jsx("div",{className:"space-y-3",children:m.map(g=>t.jsxs("div",{className:"flex gap-4 p-3 bg-zinc-800 hover:bg-zinc-700 rounded-lg transition-colors group",children:[t.jsx("img",{src:g.thumbnail_url,alt:g.title,className:"w-32 h-20 object-cover rounded flex-shrink-0"}),t.jsxs("div",{className:"flex-1 min-w-0",children:[t.jsx("h4",{className:"font-medium truncate",children:g.title}),t.jsx("p",{className:"text-sm text-zinc-400",children:g.channel}),t.jsx("p",{className:"text-sm text-zinc-500",children:gr(g.duration)})]}),t.jsxs("div",{className:"flex items-center gap-2",children:[t.jsx("a",{href:g.url,target:"_blank",rel:"noopener noreferrer",className:"p-2 hover:bg-zinc-600 rounded-full transition-colors",title:"Open in YouTube",children:t.jsx(rs,{className:"w-5 h-5"})}),t.jsx("button",{onClick:()=>b(g),disabled:M.isPending,className:"p-2 bg-green-600 hover:bg-green-500 rounded-full transition-colors disabled:opacity-50",title:"Download this video",children:M.isPending?t.jsx(ue,{className:"w-5 h-5 animate-spin"}):t.jsx(as,{className:"w-5 h-5"})})]})]},g.video_id))}):t.jsx("p",{className:"text-center text-zinc-500 py-12",children:"No videos found for this track"}),t.jsx("button",{onClick:()=>i(!1),className:"mt-6 text-zinc-400 hover:text-white transition-colors",children:"Cancel"})]})}):l?.download_status==="downloading"||l?.download_status==="pending"?t.jsxs("div",{className:"w-full h-full flex flex-col items-center justify-center bg-zinc-900",children:[t.jsx(ue,{className:"w-12 h-12 animate-spin text-green-500 mb-4"}),t.jsx("p",{className:"text-white text-lg",children:"Downloading video..."}),t.jsx("div",{className:"w-48 sm:w-64 h-2 bg-zinc-700 rounded-full mt-4 overflow-hidden",children:t.jsx("div",{className:"h-full bg-green-500 transition-all duration-300",style:{width:`${l.progress||0}%`}})}),t.jsxs("p",{className:"text-zinc-400 mt-2",children:[Math.round(l.progress||0),"%"]})]}):l?.download_status==="error"?t.jsxs("div",{className:"w-full h-full flex flex-col items-center justify-center bg-zinc-900",children:[t.jsx(ce,{className:"w-16 h-16 text-red-500 mb-4 opacity-50"}),t.jsx("p",{className:"text-red-400",children:"Download failed"}),t.jsx("p",{className:"text-sm text-zinc-500 mt-2",children:l.error}),t.jsx("button",{onClick:v,className:"mt-4 px-4 py-2 bg-zinc-800 hover:bg-zinc-700 rounded-lg transition-colors",children:"Try again"})]}):t.jsxs("div",{className:"w-full h-full flex flex-col items-center justify-center bg-zinc-900",children:[t.jsx(ce,{className:"w-16 h-16 text-zinc-600 mb-4"}),t.jsx("p",{className:"text-zinc-400 mb-4",children:"No music video available"}),t.jsxs("button",{onClick:v,className:"flex items-center gap-2 px-4 py-2 bg-green-600 hover:bg-green-500 rounded-lg transition-colors",children:[t.jsx(is,{className:"w-5 h-5"}),"Find music video"]}),t.jsx("p",{className:"text-sm text-zinc-600 mt-4",children:"Search YouTube for the official music video"})]}):t.jsx("div",{className:"w-full h-full flex items-center justify-center bg-zinc-900",children:t.jsx(ce,{className:"w-16 h-16 text-zinc-600"})})}ae({id:"music-video",name:"Music Video",description:"Search and play synced music videos from YouTube",usesMetadata:!1},xr);const Ke={"cosmic-orb":ve,"frequency-bars":cs,"album-kaleidoscope":ls,"color-flow":os,"typography-wave":ns,"lyric-pulse":it,"music-video":ce};function vr(){const[s,e]=f.useState(!1),r=f.useRef(null),{visualizerId:a,setVisualizerId:i}=Ae(),n=Qt(),c=n.find(h=>h.metadata.id===a);f.useEffect(()=>{const h=m=>{r.current&&!r.current.contains(m.target)&&e(!1)};if(s)return document.addEventListener("mousedown",h),()=>document.removeEventListener("mousedown",h)},[s]),f.useEffect(()=>{const h=m=>{m.key==="Escape"&&e(!1)};if(s)return document.addEventListener("keydown",h),()=>document.removeEventListener("keydown",h)},[s]);const u=h=>{i(h),e(!1)},l=c?Ke[c.metadata.id]||ve:ve;return t.jsxs("div",{ref:r,className:"relative",children:[t.jsxs("button",{onClick:()=>e(!s),className:`flex items-center gap-2 px-3 py-2 rounded-lg transition-colors ${s?"bg-white/20 text-white":"bg-white/10 text-zinc-300 hover:bg-white/15 hover:text-white"}`,children:[t.jsx(l,{className:"w-4 h-4"}),t.jsx("span",{className:"text-sm font-medium",children:c?.metadata.name||"Visualizer"}),t.jsx(nt,{className:`w-4 h-4 transition-transform ${s?"rotate-180":""}`})]}),s&&t.jsxs("div",{className:"absolute top-full right-0 mt-2 w-[calc(100vw-2rem)] sm:w-64 max-w-64 bg-zinc-900 border border-zinc-700 rounded-lg shadow-xl z-50 overflow-hidden",children:[t.jsx("div",{className:"p-2 border-b border-zinc-700",children:t.jsx("span",{className:"text-xs text-zinc-500 uppercase tracking-wide",children:"Choose Visualizer"})}),t.jsx("div",{className:"max-h-80 overflow-y-auto",children:n.map(({metadata:h})=>{const m=Ke[h.id]||ve,o=h.id===a;return t.jsxs("button",{onClick:()=>u(h.id),className:`w-full flex items-start gap-3 p-3 text-left transition-colors ${o?"bg-purple-500/20 text-white":"text-zinc-300 hover:bg-white/5 hover:text-white"}`,children:[t.jsx("div",{className:`p-2 rounded-lg ${o?"bg-purple-500/30":"bg-zinc-800"}`,children:t.jsx(m,{className:"w-4 h-4"})}),t.jsxs("div",{className:"flex-1 min-w-0",children:[t.jsxs("div",{className:"font-medium flex items-center gap-2",children:[h.name,h.usesMetadata&&t.jsx("span",{className:"text-[10px] px-1.5 py-0.5 bg-purple-500/30 text-purple-300 rounded",children:"METADATA"})]}),t.jsx("div",{className:"text-xs text-zinc-500 mt-0.5",children:h.description})]}),o&&t.jsx("div",{className:"w-2 h-2 rounded-full bg-purple-500 mt-2"})]},h.id)})})]})]})}function br(){return t.jsx("div",{className:"w-full h-full bg-[#0a0015] flex items-center justify-center",children:t.jsx("div",{className:"w-16 h-16 border-4 border-purple-500 border-t-transparent rounded-full animate-spin"})})}function Mr(){return t.jsxs("div",{className:"w-full h-full bg-[#0a0015] flex flex-col items-center justify-center gap-4",children:[t.jsx("p",{className:"text-zinc-400 text-sm",children:"Visualizer failed to load"}),t.jsxs("button",{onClick:()=>window.location.reload(),className:`flex items-center gap-2 px-4 py-2 bg-zinc-800 hover:bg-zinc-700
                   rounded-lg text-sm text-zinc-300 transition-colors`,children:[t.jsx(us,{className:"w-4 h-4"}),"Reload"]})]})}function yr({track:s=null,artworkUrl:e=null,lyrics:r=null,isPlaying:a=!1,features:i=null,className:n=""}){const{visualizerId:c}=Ae(),u=Ve(c)||Ve(Je);if(!u)return t.jsx("div",{className:`w-full h-full bg-[#0a0015] flex items-center justify-center ${n}`,children:t.jsx("span",{className:"text-zinc-500",children:"No visualizer available"})});const l=u.component;return t.jsx("div",{className:`w-full h-full ${n}`,children:t.jsx(Ht,{name:"visualizer",fallback:t.jsx(Mr,{}),children:t.jsx(f.Suspense,{fallback:t.jsx(br,{}),children:t.jsx(l,{track:s,artworkUrl:e,lyrics:r,currentTime:0,duration:0,isPlaying:a,features:i})})})})}function wr(){const[s,e]=f.useState(!1),r=f.useRef(null),a=f.useRef(null),i=Yt(),n=le(o=>o.masterEnabled),c=le(o=>o.setMasterEnabled),u=le(o=>o.presets),l=le(o=>o.activePresetName),h=le(o=>o.loadPreset);f.useEffect(()=>{const o=d=>{r.current&&a.current&&!r.current.contains(d.target)&&!a.current.contains(d.target)&&e(!1)};if(s)return document.addEventListener("mousedown",o),()=>document.removeEventListener("mousedown",o)},[s]);const m=["Warm Vinyl","Live Concert","Studio Polish","Bass Boost","Dreamy"];return i?t.jsxs("div",{className:"relative",children:[t.jsx("button",{ref:a,onClick:()=>e(!s),className:`p-2 rounded-md transition-colors ${n?"bg-purple-500/20 text-purple-400":"text-zinc-400 hover:text-white hover:bg-white/10"}`,title:"Audio Effects",children:t.jsx(fs,{className:"w-5 h-5"})}),s&&t.jsxs("div",{ref:r,className:"absolute top-full right-0 mt-2 w-56 bg-zinc-900 border border-zinc-700 rounded-lg shadow-xl z-50",children:[t.jsx("div",{className:"p-3 border-b border-zinc-700",children:t.jsxs("div",{className:"flex items-center justify-between",children:[t.jsx("span",{className:"text-sm font-medium text-white",children:"Audio Effects"}),t.jsxs("label",{className:"relative inline-flex items-center cursor-pointer",children:[t.jsx("input",{type:"checkbox",checked:n,onChange:o=>c(o.target.checked),className:"sr-only peer"}),t.jsx("div",{className:"w-9 h-5 bg-zinc-600 peer-focus:outline-none peer-focus:ring-2 peer-focus:ring-purple-500 rounded-full peer peer-checked:after:translate-x-full peer-checked:after:border-white after:content-[''] after:absolute after:top-[2px] after:left-[2px] after:bg-white after:rounded-full after:h-4 after:w-4 after:transition-all peer-checked:bg-purple-500"})]})]})}),n&&t.jsxs("div",{className:"p-2",children:[t.jsx("p",{className:"text-xs text-zinc-500 px-2 py-1",children:"Quick Presets"}),t.jsx("div",{className:"space-y-0.5",children:u.filter(o=>m.includes(o.name)).map(o=>t.jsx("button",{onClick:()=>{h(o.name),e(!1)},className:`w-full text-left px-3 py-2 text-sm rounded-md transition-colors ${l===o.name?"bg-purple-500/20 text-purple-400":"text-zinc-300 hover:bg-zinc-800"}`,children:o.name},o.name))}),u.some(o=>!m.includes(o.name))&&t.jsxs(t.Fragment,{children:[t.jsx("p",{className:"text-xs text-zinc-500 px-2 py-1 mt-2",children:"Custom"}),t.jsx("div",{className:"space-y-0.5",children:u.filter(o=>!m.includes(o.name)).map(o=>t.jsx("button",{onClick:()=>{h(o.name),e(!1)},className:`w-full text-left px-3 py-2 text-sm rounded-md transition-colors ${l===o.name?"bg-purple-500/20 text-purple-400":"text-zinc-300 hover:bg-zinc-800"}`,children:o.name},o.name))})]})]}),t.jsx("div",{className:"p-2 border-t border-zinc-700",children:t.jsx("button",{onClick:()=>{e(!1),window.dispatchEvent(new Event("navigate-to-settings"))},className:"block w-full text-center text-xs text-zinc-400 hover:text-white py-1 transition-colors",children:"More options in Settings"})})]})]}):null}function Ze(s){if(!s||!isFinite(s))return"0:00";const e=Math.floor(s/60),r=Math.floor(s%60);return`${e}:${r.toString().padStart(2,"0")}`}function _r({isOpen:s,onClose:e}){const[r,a]=f.useState(!1),[i,n]=f.useState(null),[c,u]=f.useState(Ge),[l,h]=f.useState(!1),[m,o]=f.useState(!0),d=f.useRef(null),p=f.useRef(void 0),{navigateToArtist:M,navigateToAlbum:R}=Xt(),{currentTrack:v,isPlaying:b,isLoadingAudio:g,currentTime:x,duration:T,volume:C,shuffle:_,repeat:w,consume:k,isPreview:P}=Y(Wt(j=>({currentTrack:j.currentTrack,isPlaying:j.isPlaying,isLoadingAudio:j.isLoadingAudio,currentTime:j.currentTime,duration:j.duration,volume:j.volume,shuffle:j.shuffle,repeat:j.repeat,consume:j.consume,isPreview:j.queueIndex>=0&&j.queue[j.queueIndex]?.externalInfo!=null}))),S=Y(j=>j.setVolume),z=Y(j=>j.playNext),A=Y(j=>j.playPrevious),E=Y(j=>j.toggleShuffle),Q=Y(j=>j.toggleRepeat),J=Y(j=>j.toggleConsume),$=Y(j=>j.addToQueue),{seek:y,togglePlayPause:N}=Kt(),{isFavorite:D,toggle:O}=Zt(),{visualizerId:ee}=Ae(),te=Jt();f.useEffect(()=>{v&&te(v.artist,v.album,v.id)},[v,te]);const X=f.useCallback(j=>{v&&(j.preventDefault(),u({isOpen:!0,track:v,position:{x:j.clientX,y:j.clientY}}))},[v]),je=f.useCallback(()=>{u(Ge)},[]);f.useEffect(()=>{if(!v){n(null);return}$e.getLyrics(v.id).then(j=>{j.synced&&j.lines.length>0?n(j.lines):n(null)}).catch(()=>n(null))},[v?.id]),f.useEffect(()=>{a(!1)},[v?.id]);const q=f.useRef(null),ut=f.useCallback(j=>{q.current={y:j.touches[0].clientY,time:Date.now()}},[]),ft=f.useCallback(j=>{if(!q.current)return;const H=j.changedTouches[0].clientY-q.current.y,Ce=Date.now()-q.current.time,pt=H/Ce;(H>50||pt>.3)&&e(),q.current=null},[e]),ht=f.useCallback(()=>{document.fullscreenElement?document.exitFullscreen():d.current?.requestFullscreen()},[]);f.useEffect(()=>{const j=()=>{const H=!!document.fullscreenElement;h(H),H||(o(!0),p.current&&clearTimeout(p.current))};return document.addEventListener("fullscreenchange",j),()=>{document.removeEventListener("fullscreenchange",j),p.current&&clearTimeout(p.current)}},[]);const Be=f.useCallback(()=>{l&&(o(!0),p.current&&clearTimeout(p.current),p.current=setTimeout(()=>o(!1),3e3))},[l]);f.useEffect(()=>(l&&(p.current=setTimeout(()=>o(!1),3e3)),()=>{p.current&&clearTimeout(p.current)}),[l]);const dt=T>0?x/T*100:0,mt=j=>{const H=j.currentTarget.getBoundingClientRect(),Ce=(j.clientX-H.left)/H.width;y(Ce*T)};if(!v)return null;const Ee=$e.getArtworkUrl(v.id);return t.jsxs("div",{ref:d,onMouseMove:l?Be:void 0,onTouchStart:l?Be:void 0,className:`fixed inset-0 z-50 bg-black flex flex-col overflow-hidden transition-transform duration-300 ease-out ${s?"translate-y-0":"translate-y-full pointer-events-none"} ${l&&!m?"cursor-none":""}`,children:[t.jsxs("div",{className:`absolute top-0 left-0 right-0 z-10 flex items-center justify-between p-4 pt-safe bg-gradient-to-b from-black/80 to-transparent transition-opacity duration-300 ${l&&!m?"opacity-0 pointer-events-none":"opacity-100"}`,onTouchStart:ut,onTouchEnd:ft,children:[t.jsx("button",{onClick:e,className:"p-2 hover:bg-white/10 rounded-full transition-colors","aria-label":"Close player",children:t.jsx(nt,{className:"w-6 h-6"})}),t.jsxs("div",{className:"flex items-center gap-3",children:[t.jsx(vr,{}),t.jsx(wr,{})]}),!W()&&t.jsx("button",{onClick:ht,className:"p-2 hover:bg-white/10 rounded-full transition-colors","aria-label":l?"Exit fullscreen":"Enter fullscreen",children:l?t.jsx(hs,{className:"w-5 h-5"}):t.jsx(ds,{className:"w-5 h-5"})})]}),t.jsx("div",{className:"flex-1 relative overflow-hidden",children:t.jsx(yr,{track:v,artworkUrl:Ee,lyrics:i,isPlaying:b,className:"absolute inset-0"})}),!(l&&!m)&&t.jsx("div",{className:"absolute bottom-64 left-8 z-20",children:r?t.jsx("div",{className:"w-24 h-24 bg-zinc-800 rounded-lg flex items-center justify-center shadow-2xl",children:t.jsx(it,{className:"w-12 h-12 text-zinc-600"})}):t.jsx("img",{src:Ee,alt:"Album art",className:"w-24 h-24 rounded-lg shadow-2xl object-cover",onError:()=>a(!0)})}),t.jsxs("div",{className:`absolute bottom-0 left-0 right-0 z-10 bg-gradient-to-t from-black via-black/95 to-transparent p-4 pt-8 sm:p-6 sm:pt-16 transition-opacity duration-300 ${l&&!m?"opacity-0 pointer-events-none":"opacity-100"}`,style:{paddingBottom:"calc(1.5rem + env(safe-area-inset-bottom, 0px))"},children:[t.jsxs("div",{className:"text-center mb-3 sm:mb-6",onContextMenu:X,children:[t.jsxs("div",{className:"flex items-center justify-center gap-2",children:[t.jsx("h2",{className:"text-xl sm:text-2xl font-bold truncate",children:v.title||"Unknown"}),P&&t.jsx("span",{className:"flex-shrink-0 px-2 py-0.5 text-[10px] font-semibold uppercase tracking-wider bg-amber-500/20 text-amber-400 rounded-full",children:"Preview"}),t.jsx("button",{onClick:X,className:"p-1.5 text-zinc-400 hover:text-white hover:bg-white/10 rounded-full transition-colors flex-shrink-0","aria-label":"More options",children:t.jsx(ms,{className:"w-5 h-5"})})]}),v.artist?t.jsx("button",{onClick:()=>{e(),M(v.artist)},className:"text-lg text-zinc-400 hover:text-zinc-200 hover:underline transition-colors",children:v.artist}):t.jsx("p",{className:"text-lg text-zinc-400",children:"Unknown"}),v.album?t.jsx("button",{onClick:()=>{e(),R(v.artist,v.album)},className:"text-sm text-zinc-500 hover:text-zinc-300 hover:underline transition-colors",children:v.album}):null]}),t.jsxs("div",{className:"mb-3 sm:mb-6",children:[t.jsx("div",{className:"py-3 cursor-pointer group",onClick:mt,children:t.jsx("div",{className:"h-1.5 bg-zinc-700 rounded-full",children:t.jsx("div",{className:"h-full bg-white rounded-full relative group-hover:bg-green-500 transition-colors",style:{width:`${dt}%`},children:t.jsx("div",{className:"absolute right-0 top-1/2 -translate-y-1/2 w-4 h-4 bg-white rounded-full opacity-0 group-hover:opacity-100 transition-opacity shadow-lg"})})})}),t.jsxs("div",{className:"flex justify-between text-sm text-zinc-400 mt-2",children:[t.jsx("span",{children:Ze(x)}),t.jsx("span",{children:Ze(T)})]})]}),t.jsxs("div",{className:"flex items-center justify-center gap-3 sm:gap-6",children:[t.jsx("button",{onClick:E,className:`p-3 rounded-full transition-colors ${_?"text-green-500":"text-zinc-400 hover:text-white"}`,"aria-label":_?"Disable shuffle":"Enable shuffle","aria-pressed":_,children:t.jsx(ps,{className:"w-5 h-5"})}),t.jsx("button",{onClick:A,className:"p-3 hover:bg-white/10 rounded-full transition-colors","aria-label":"Previous track",children:t.jsx(gs,{className:"w-7 h-7",fill:"currentColor"})}),t.jsx("button",{onClick:N,className:"p-5 bg-white text-black rounded-full hover:scale-105 transition-transform shadow-lg","aria-label":g?"Loading":b?"Pause":"Play",children:g?t.jsx(ue,{className:"w-8 h-8 animate-spin"}):b?t.jsx(xs,{className:"w-8 h-8",fill:"currentColor"}):t.jsx(vs,{className:"w-8 h-8",fill:"currentColor"})}),t.jsx("button",{onClick:z,className:"p-3 hover:bg-white/10 rounded-full transition-colors","aria-label":"Next track",children:t.jsx(bs,{className:"w-7 h-7",fill:"currentColor"})}),t.jsx("button",{onClick:Q,className:`p-3 rounded-full transition-colors ${w!=="off"?"text-green-500":"text-zinc-400 hover:text-white"}`,"aria-label":`Repeat: ${w}`,"aria-pressed":w!=="off",children:t.jsx(Ms,{className:"w-5 h-5"})}),!W()&&t.jsx("button",{onClick:J,className:`p-3 rounded-full transition-colors ${k?"text-green-500":"text-zinc-400 hover:text-white"}`,"aria-label":k?"Disable consume mode":"Enable consume mode","aria-pressed":k,title:"Consume: remove tracks after playing",children:t.jsx(ys,{className:"w-5 h-5"})})]}),!W()&&t.jsxs("div",{className:"flex items-center justify-center gap-3 mt-6",children:[t.jsx("button",{onClick:()=>S(C>0?0:1),className:"p-2 text-zinc-400 hover:text-white transition-colors","aria-label":C===0?"Unmute":"Mute",children:C===0?t.jsx(ws,{className:"w-5 h-5"}):t.jsx(js,{className:"w-5 h-5"})}),t.jsx("input",{type:"range",min:"0",max:"1",step:"0.01",value:C,onChange:j=>S(parseFloat(j.target.value)),className:"w-24 sm:w-32 accent-white","aria-label":"Volume"})]})]}),c.isOpen&&c.track&&t.jsx(es,{track:c.track,position:c.position,isSelected:!1,onClose:je,onPlay:()=>{},onQueue:()=>{c.track&&$(c.track)},onGoToArtist:()=>{c.track?.artist&&(e(),M(c.track.artist))},onGoToAlbum:()=>{c.track?.artist&&c.track?.album&&(e(),R(c.track.artist,c.track.album))},onToggleSelect:()=>{},onAddToPlaylist:()=>{c.track&&qe.getState().openPlaylistPicker([c.track.id])},onMakePlaylist:()=>{if(c.track){const j=c.track,H=`Make me a playlist based on "${j.title||"this track"}" by ${j.artist||"Unknown Artist"}`;qe.getState().triggerChat(H),e()}},onEditMetadata:()=>{c.track&&ts.getState().setEditingTrackId(c.track.id)},isFavorite:c.track?D(c.track.id):!1,onToggleFavorite:()=>{c.track&&O(c.track.id)}})]})}export{_r as FullPlayer};

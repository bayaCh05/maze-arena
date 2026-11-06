import * as THREE from 'three';
import { EffectComposer } from 'three/addons/postprocessing/EffectComposer.js';
import { OutputPass } from 'three/addons/postprocessing/OutputPass.js';
import { RenderPass } from 'three/addons/postprocessing/RenderPass.js';
import { UnrealBloomPass } from 'three/addons/postprocessing/UnrealBloomPass.js';
import { CSS2DRenderer } from 'three/addons/renderers/CSS2DRenderer.js';

/**
 * Renderer + bloom (only bright emissive parts pass the threshold: trim, pellets, auras) +
 * the CSS2D layer for name labels. Keeps the camera framing the whole maze on any aspect.
 */
export class RenderPipeline {
  readonly camera = new THREE.PerspectiveCamera(38, 1, 0.1, 200);
  private readonly composer: EffectComposer;
  private readonly bloom: UnrealBloomPass;
  private readonly labels = new CSS2DRenderer();
  private mazeW = 20;
  private mazeH = 15;
  private width = 0;
  private height = 0;
  maxDpr = 2;
  /** Portrait screens: the camera turns 90 degrees so the maze's long side runs up the screen. */
  rotated = false;

  constructor(
    readonly renderer: THREE.WebGLRenderer,
    private readonly scene: THREE.Scene,
    labelHost: HTMLElement,
  ) {
    renderer.toneMapping = THREE.ACESFilmicToneMapping;
    renderer.toneMappingExposure = 1.1;
    renderer.shadowMap.type = THREE.PCFSoftShadowMap;
    this.composer = new EffectComposer(renderer);
    this.composer.addPass(new RenderPass(scene, this.camera));
    this.bloom = new UnrealBloomPass(new THREE.Vector2(256, 256), 0.85, 0.5, 0.78);
    this.composer.addPass(this.bloom);
    this.composer.addPass(new OutputPass());
    this.labels.domElement.className = 'label-layer';
    labelHost.appendChild(this.labels.domElement);
    if (matchMedia('(pointer: coarse)').matches) this.maxDpr = 1.5;
  }

  frameMaze(width: number, height: number): void {
    this.mazeW = width;
    this.mazeH = height;
    this.width = 0; // force a re-fit on the next resize check
  }

  /** Resize buffers and re-fit the camera when the canvas size changed. */
  resize(): void {
    const canvas = this.renderer.domElement;
    const w = Math.max(1, canvas.clientWidth);
    const h = Math.max(1, canvas.clientHeight);
    if (w === this.width && h === this.height) return;
    this.width = w;
    this.height = h;
    const dpr = Math.min(window.devicePixelRatio || 1, this.maxDpr);
    this.renderer.setPixelRatio(dpr);
    this.renderer.setSize(w, h, false);
    this.composer.setPixelRatio(dpr);
    this.composer.setSize(w, h);
    this.bloom.resolution.set(w * dpr * 0.5, h * dpr * 0.5);
    this.labels.setSize(w, h);
    this.camera.aspect = w / h;
    this.fitCamera();
  }

  /**
   * Angled top-down view: the whole maze (plus a margin) fits horizontally and vertically.
   * Landscape: camera on the +Z side (grid rows run down the screen). Portrait: camera on the
   * +X side, so grid columns run up the screen; screenToGrid() maps swipes accordingly.
   */
  private fitCamera(): void {
    this.rotated = this.camera.aspect < 0.85;
    const pitch = THREE.MathUtils.degToRad(this.rotated ? 64 : 58);
    const vfov = THREE.MathUtils.degToRad(this.camera.fov);
    const hfov = 2 * Math.atan(Math.tan(vfov / 2) * this.camera.aspect);
    const margin = this.rotated ? 1.04 : 1.08;
    const across = this.rotated ? this.mazeH : this.mazeW;
    const deep = this.rotated ? this.mazeW : this.mazeH;
    const halfW = (across / 2) * margin;
    const halfD = (deep / 2) * margin;
    // Depth seen at a pitch shrinks by sin(pitch); walls add a little height to the near rows.
    const distW = halfW / Math.tan(hfov / 2);
    const distH = (halfD * Math.sin(pitch) + 0.6) / Math.tan(vfov / 2);
    const dist = Math.max(distW, distH) + halfD * Math.cos(pitch) * 0.5;
    const back = Math.cos(pitch) * dist;
    this.camera.position.set(this.rotated ? back : 0, Math.sin(pitch) * dist, this.rotated ? 0 : back);
    this.camera.lookAt(this.rotated ? 0.35 : 0, 0, this.rotated ? 0 : 0.35);
    this.camera.updateProjectionMatrix();
  }

  /** A direction as the player sees it on screen -> the grid direction the server expects. */
  screenToGrid<D extends 'UP' | 'DOWN' | 'LEFT' | 'RIGHT'>(dir: D): 'UP' | 'DOWN' | 'LEFT' | 'RIGHT' {
    if (!this.rotated) return dir;
    // Camera on +X looking at -X: screen up = grid LEFT, screen right = grid UP.
    return ({ UP: 'LEFT', RIGHT: 'UP', DOWN: 'RIGHT', LEFT: 'DOWN' } as const)[dir];
  }

  render(): void {
    this.resize();
    // Count the whole frame (scene + post passes), not just the last full-screen pass.
    this.renderer.info.autoReset = false;
    this.renderer.info.reset();
    this.composer.render();
    this.labels.render(this.scene, this.camera);
  }

  dispose(): void {
    this.composer.dispose();
    this.bloom.dispose();
    this.labels.domElement.remove();
  }
}

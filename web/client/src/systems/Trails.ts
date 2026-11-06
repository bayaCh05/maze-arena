import * as THREE from 'three';

const MAX_MARKS = 240;
const LIFE = 0.9; // seconds a trail mark takes to fade
const SPACING = 0.2; // world units between two marks

/**
 * Neon light trails on the floor: each chomper drops a soft glowing mark every SPACING of
 * travel, in its colour, fading out over LIFE. One additive InstancedMesh for every player;
 * fading is done by darkening the instance colour (additive black = invisible).
 */
export class Trails {
  readonly mesh: THREE.InstancedMesh;
  private readonly geo = new THREE.PlaneGeometry(1, 1);
  private readonly tex: THREE.CanvasTexture;
  private readonly mat: THREE.MeshBasicMaterial;
  private readonly life = new Float32Array(MAX_MARKS);
  private readonly base: THREE.Color[] = [];
  private readonly pos: THREE.Vector3[] = [];
  private readonly last = new Map<string, THREE.Vector3>();
  private readonly tmp = new THREE.Object3D();
  private readonly color = new THREE.Color();
  private next = 0;

  constructor() {
    const c = document.createElement('canvas');
    c.width = c.height = 64;
    const g = c.getContext('2d')!;
    const grad = g.createRadialGradient(32, 32, 0, 32, 32, 32);
    grad.addColorStop(0, 'rgba(255,255,255,1)');
    grad.addColorStop(0.35, 'rgba(255,255,255,0.55)');
    grad.addColorStop(1, 'rgba(255,255,255,0)');
    g.fillStyle = grad;
    g.fillRect(0, 0, 64, 64);
    this.tex = new THREE.CanvasTexture(c);
    this.tex.colorSpace = THREE.SRGBColorSpace;
    this.mat = new THREE.MeshBasicMaterial({
      map: this.tex,
      transparent: true,
      depthWrite: false,
      blending: THREE.AdditiveBlending,
      toneMapped: false,
    });
    this.mesh = new THREE.InstancedMesh(this.geo, this.mat, MAX_MARKS);
    this.mesh.name = 'lightTrails';
    this.mesh.frustumCulled = false;
    for (let i = 0; i < MAX_MARKS; i += 1) {
      this.base.push(new THREE.Color());
      this.pos.push(new THREE.Vector3());
      this.hide(i);
    }
    this.mesh.instanceColor = new THREE.InstancedBufferAttribute(new Float32Array(MAX_MARKS * 3), 3);
  }

  /** Call every frame with each chomper's current position. */
  follow(name: string, at: THREE.Vector3, color: THREE.Color): void {
    const prev = this.last.get(name);
    if (!prev) {
      this.last.set(name, at.clone());
      return;
    }
    const d = prev.distanceTo(at);
    if (d > 1.5) {
      prev.copy(at); // snapped (respawn): no trail across the maze
      return;
    }
    if (d < SPACING) return;
    prev.copy(at);
    const i = this.next;
    this.next = (this.next + 1) % MAX_MARKS;
    this.life[i] = LIFE;
    this.base[i].copy(color);
    this.pos[i].set(at.x, 0.03, at.z);
  }

  forget(name: string): void {
    this.last.delete(name);
  }

  update(delta: number): void {
    for (let i = 0; i < MAX_MARKS; i += 1) {
      if (this.life[i] <= 0) continue;
      this.life[i] = Math.max(0, this.life[i] - delta);
      const k = this.life[i] / LIFE;
      if (k <= 0) {
        this.hide(i);
        continue;
      }
      this.tmp.position.copy(this.pos[i]);
      this.tmp.rotation.set(-Math.PI / 2, 0, 0);
      this.tmp.scale.setScalar(0.35 + 0.4 * k);
      this.tmp.updateMatrix();
      this.mesh.setMatrixAt(i, this.tmp.matrix);
      this.mesh.setColorAt(i, this.color.copy(this.base[i]).multiplyScalar(0.75 * k * k));
    }
    this.mesh.instanceMatrix.needsUpdate = true;
    if (this.mesh.instanceColor) this.mesh.instanceColor.needsUpdate = true;
  }

  private hide(i: number): void {
    this.tmp.position.set(0, -50, 0);
    this.tmp.scale.setScalar(0);
    this.tmp.updateMatrix();
    this.mesh.setMatrixAt(i, this.tmp.matrix);
  }

  dispose(): void {
    this.geo.dispose();
    this.mat.dispose();
    this.tex.dispose();
    this.mesh.dispose();
    this.mesh.removeFromParent();
  }
}

import * as THREE from 'three';
import type { Random } from '../utils/random';

const MAX_SPARKS = 400;
const MAX_RINGS = 8;

/** Pooled event VFX: spark bursts (pellet eaten, player eaten) and expanding shock rings (power). */
export class Vfx {
  readonly root = new THREE.Group();
  private readonly positions = new Float32Array(MAX_SPARKS * 3);
  private readonly colors = new Float32Array(MAX_SPARKS * 3);
  private readonly velocity = new Float32Array(MAX_SPARKS * 3);
  private readonly life = new Float32Array(MAX_SPARKS);
  private readonly sparkGeo = new THREE.BufferGeometry();
  private readonly sparkMat: THREE.PointsMaterial;
  private readonly rings: { mesh: THREE.Mesh; mat: THREE.MeshBasicMaterial; t: number }[] = [];
  private readonly ringGeo = new THREE.RingGeometry(0.85, 1, 48);
  private next = 0;

  constructor(private rng: Random) {
    this.sparkGeo.setAttribute('position', new THREE.BufferAttribute(this.positions, 3));
    this.sparkGeo.setAttribute('color', new THREE.BufferAttribute(this.colors, 3));
    this.sparkMat = new THREE.PointsMaterial({
      size: 0.12,
      vertexColors: true,
      transparent: true,
      depthWrite: false,
      blending: THREE.AdditiveBlending,
    });
    const points = new THREE.Points(this.sparkGeo, this.sparkMat);
    points.name = 'sparks';
    points.frustumCulled = false;
    this.root.add(points);
    for (let i = 0; i < MAX_RINGS; i += 1) {
      const mat = new THREE.MeshBasicMaterial({ transparent: true, depthWrite: false, blending: THREE.AdditiveBlending });
      const mesh = new THREE.Mesh(this.ringGeo, mat);
      mesh.name = 'shockRing';
      mesh.rotation.x = -Math.PI / 2;
      mesh.visible = false;
      this.root.add(mesh);
      this.rings.push({ mesh, mat, t: 1 });
    }
    this.life.fill(0);
    this.positions.fill(-999);
  }

  setRandom(rng: Random): void {
    this.rng = rng;
  }

  burst(at: THREE.Vector3, color: string, count: number, speed = 2.2): void {
    const c = new THREE.Color(color);
    for (let k = 0; k < count; k += 1) {
      const i = this.next;
      this.next = (this.next + 1) % MAX_SPARKS;
      const a = this.rng() * Math.PI * 2;
      const up = 0.6 + this.rng() * 1.4;
      const s = speed * (0.4 + this.rng() * 0.8);
      this.positions.set([at.x, at.y + 0.3, at.z], i * 3);
      this.velocity.set([Math.cos(a) * s, up * speed * 0.6, Math.sin(a) * s], i * 3);
      this.colors.set([c.r, c.g, c.b], i * 3);
      this.life[i] = 0.45 + this.rng() * 0.35;
    }
  }

  shock(at: THREE.Vector3, color: string): void {
    const ring = this.rings.find((r) => r.t >= 1) ?? this.rings[0];
    ring.t = 0;
    ring.mat.color.set(color);
    ring.mesh.position.set(at.x, 0.05, at.z);
    ring.mesh.visible = true;
  }

  update(delta: number): void {
    for (let i = 0; i < MAX_SPARKS; i += 1) {
      if (this.life[i] <= 0) continue;
      this.life[i] -= delta;
      const j = i * 3;
      this.velocity[j + 1] -= 7 * delta;
      this.positions[j] += this.velocity[j] * delta;
      this.positions[j + 1] = Math.max(0.03, this.positions[j + 1] + this.velocity[j + 1] * delta);
      this.positions[j + 2] += this.velocity[j + 2] * delta;
      if (this.life[i] <= 0) this.positions[j + 1] = -999;
    }
    this.sparkGeo.attributes.position.needsUpdate = true;
    for (const r of this.rings) {
      if (r.t >= 1) continue;
      r.t = Math.min(1, r.t + delta * 1.8);
      r.mesh.scale.setScalar(0.3 + r.t * 2.6);
      r.mat.opacity = 1 - r.t;
      r.mesh.visible = r.t < 1;
    }
  }

  clear(): void {
    this.life.fill(0);
    this.positions.fill(-999);
    this.sparkGeo.attributes.position.needsUpdate = true;
    for (const r of this.rings) {
      r.t = 1;
      r.mesh.visible = false;
    }
  }

  dispose(): void {
    this.sparkGeo.dispose();
    this.sparkMat.dispose();
    this.ringGeo.dispose();
    for (const r of this.rings) r.mat.dispose();
  }
}

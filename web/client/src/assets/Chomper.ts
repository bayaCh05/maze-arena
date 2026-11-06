import * as THREE from 'three';
import { CSS2DObject } from 'three/addons/renderers/CSS2DRenderer.js';
import type { MaterialLibrary } from './Materials';

const R = 0.4;

/**
 * A player: two hemispheres hinged at the centre (the mouth opens toward local +Z), eyes on
 * the upper jaw, a contact shadow, a power aura ring, a "you" marker and a name label.
 * Only visuals: position and power state come from the server's STATE.
 */
export class Chomper {
  readonly root = new THREE.Group();
  private readonly body = new THREE.Group();
  private readonly upper = new THREE.Group();
  private readonly lower = new THREE.Group();
  private readonly skin: THREE.MeshStandardMaterial;
  private readonly auraMat: THREE.MeshStandardMaterial;
  private readonly aura: THREE.Mesh;
  private readonly youRing: THREE.Mesh | null = null;
  private readonly label: CSS2DObject;
  private readonly geometries: THREE.BufferGeometry[] = [];
  private readonly baseColor: THREE.Color;
  private readonly vulnerableColor = new THREE.Color('#4d6dff');
  private readonly intentArrow: THREE.Mesh | null = null;
  private readonly intentMat: THREE.MeshBasicMaterial | null = null;
  private intentDir: [number, number] | null = null;
  private intentAge = 0;
  private mouth = 0.2;
  private facing = 0;
  private turnKick = 0;
  /** Gliding between two cells this frame (set by the arena's playback). */
  moving = false;

  constructor(
    readonly name: string,
    color: string,
    isYou: boolean,
    mats: MaterialLibrary,
  ) {
    this.root.name = `chomper:${name}`;
    this.baseColor = new THREE.Color(color);
    this.skin = new THREE.MeshStandardMaterial({
      color,
      emissive: color,
      emissiveIntensity: 0.28,
      roughness: 0.32,
      metalness: 0.08,
    });

    const upperGeo = new THREE.SphereGeometry(R, 40, 20, 0, Math.PI * 2, 0, Math.PI / 2);
    const lowerGeo = new THREE.SphereGeometry(R, 40, 20, 0, Math.PI * 2, Math.PI / 2, Math.PI / 2);
    const capGeo = new THREE.CircleGeometry(R * 0.98, 40);
    const eyeGeo = new THREE.SphereGeometry(0.058, 16, 12);
    const shineGeo = new THREE.SphereGeometry(0.018, 8, 6);
    const shadowGeo = new THREE.PlaneGeometry(1, 1);
    const auraGeo = new THREE.TorusGeometry(0.52, 0.035, 10, 48);
    this.geometries.push(upperGeo, lowerGeo, capGeo, eyeGeo, shineGeo, shadowGeo, auraGeo);

    const upperShell = new THREE.Mesh(upperGeo, this.skin);
    upperShell.name = 'upperJaw';
    const upperCap = new THREE.Mesh(capGeo, mats.mouth);
    upperCap.rotation.x = Math.PI / 2;
    const lowerShell = new THREE.Mesh(lowerGeo, this.skin);
    lowerShell.name = 'lowerJaw';
    const lowerCap = new THREE.Mesh(capGeo, mats.mouth);
    lowerCap.rotation.x = -Math.PI / 2;
    upperShell.castShadow = lowerShell.castShadow = true;
    this.upper.add(upperShell, upperCap);
    this.lower.add(lowerShell, lowerCap);

    for (const side of [-1, 1]) {
      const eye = new THREE.Mesh(eyeGeo, mats.eye);
      eye.name = 'eye';
      eye.position.set(side * 0.15, 0.24, 0.26);
      const shine = new THREE.Mesh(shineGeo, mats.eyeShine);
      shine.position.set(side * 0.15 + 0.02, 0.27, 0.32);
      this.upper.add(eye, shine);
    }
    this.body.add(this.upper, this.lower);
    this.body.position.y = R + 0.02;

    const shadow = new THREE.Mesh(shadowGeo, mats.contactShadow);
    shadow.name = 'contactShadow';
    shadow.rotation.x = -Math.PI / 2;
    shadow.position.y = 0.015;
    shadow.scale.setScalar(1.1);

    this.auraMat = new THREE.MeshStandardMaterial({ color, emissive: color, emissiveIntensity: 3, roughness: 0.3 });
    this.aura = new THREE.Mesh(auraGeo, this.auraMat);
    this.aura.name = 'powerAura';
    this.aura.rotation.x = Math.PI / 2;
    this.aura.position.y = 0.06;
    this.aura.visible = false;

    this.root.add(this.body, shadow, this.aura);

    if (isYou) {
      const youGeo = new THREE.RingGeometry(0.48, 0.53, 48);
      this.geometries.push(youGeo);
      const youMat = new THREE.MeshBasicMaterial({ color: '#ffffff', transparent: true, opacity: 0.7 });
      this.youRing = new THREE.Mesh(youGeo, youMat);
      this.youRing.name = 'youMarker';
      this.youRing.rotation.x = -Math.PI / 2;
      this.youRing.position.y = 0.02;
      this.root.add(this.youRing);

      // Next-turn marker: a flat chevron on the floor pointing where you last steered,
      // shown at once so input feels instant while the server's answer is on its way.
      const shape = new THREE.Shape();
      shape.moveTo(0, 0.16);
      shape.lineTo(0.17, -0.04);
      shape.lineTo(0.08, -0.04);
      shape.lineTo(0, 0.06);
      shape.lineTo(-0.08, -0.04);
      shape.lineTo(-0.17, -0.04);
      shape.closePath();
      const arrowGeo = new THREE.ShapeGeometry(shape);
      arrowGeo.rotateX(-Math.PI / 2);
      this.geometries.push(arrowGeo);
      this.intentMat = new THREE.MeshBasicMaterial({ color, transparent: true, opacity: 0, depthWrite: false, toneMapped: false });
      this.intentArrow = new THREE.Mesh(arrowGeo, this.intentMat);
      this.intentArrow.name = 'intentArrow';
      this.intentArrow.position.y = 0.04;
      this.root.add(this.intentArrow);
    }

    const el = document.createElement('div');
    el.className = `name-label${isYou ? ' is-you' : ''}`;
    el.textContent = isYou ? `${name} (you)` : name;
    el.style.setProperty('--player-color', color);
    this.label = new CSS2DObject(el);
    this.label.position.set(0, 1.45, 0);
    this.root.add(this.label);
  }

  /** Turn toward the last movement (grid direction), smoothly. */
  face(dx: number, dz: number): void {
    if (dx === 0 && dz === 0) return;
    const f = Math.atan2(dx, dz);
    if (Math.abs(Math.atan2(Math.sin(f - this.facing), Math.cos(f - this.facing))) > 0.1) this.turnKick = 1;
    this.facing = f;
    // The server took the turn we showed: hide the marker.
    if (this.intentDir && this.intentDir[0] === dx && this.intentDir[1] === dz) this.intentDir = null;
  }

  /** Show the next-turn marker (grid direction). Only the local player has one. */
  setIntent(dx: number, dz: number): void {
    if (!this.intentArrow) return;
    this.intentDir = [dx, dz];
    this.intentAge = 0;
    this.intentArrow.rotation.y = Math.atan2(-dx, -dz); // the shape points to -Z
    this.intentArrow.position.set(dx * 0.72, 0.04, dz * 0.72);
  }

  /**
   * @param power    power ticks left (aura while > 0, blinking in the last 1.5 s)
   * @param prey     a rival is powered and this player isn't: tint toward blue
   */
  update(delta: number, elapsed: number, power: number, prey: boolean): void {
    const moving = this.moving;
    const targetMouth = moving ? 0.08 + Math.abs(Math.sin(elapsed * 13)) * 0.5 : 0.18;
    this.mouth += (targetMouth - this.mouth) * Math.min(1, delta * 18);
    this.upper.rotation.x = -this.mouth;
    this.lower.rotation.x = this.mouth;

    let diff = this.facing - this.body.rotation.y;
    diff = Math.atan2(Math.sin(diff), Math.cos(diff));
    this.body.rotation.y += diff * Math.min(1, delta * 16);

    const powered = power > 0;
    this.aura.visible = powered && (power > 15 || Math.floor(elapsed * 8) % 2 === 0);
    if (powered) {
      this.aura.rotation.z = elapsed * 3;
      this.aura.scale.setScalar(1 + Math.sin(elapsed * 9) * 0.06);
    }
    // Bounce while running, a quick squash on each turn.
    const size = powered ? 1.12 : 1;
    const hop = moving ? Math.abs(Math.sin(elapsed * 15.7)) : 0;
    this.turnKick = Math.max(0, this.turnKick - delta * 6);
    const squash = 1 - this.turnKick * 0.16 + hop * 0.05;
    this.body.scale.set(size * (2 - squash), size * squash, size * (2 - squash));
    this.body.position.y = (R + 0.02) * size * squash + hop * 0.06;

    if (this.intentArrow && this.intentMat) {
      this.intentAge += delta;
      const show = this.intentDir !== null && this.intentAge < 1.6;
      const target = show ? 0.9 - 0.25 * Math.sin(elapsed * 10) ** 2 : 0;
      this.intentMat.opacity += (target - this.intentMat.opacity) * Math.min(1, delta * 14);
      this.intentArrow.visible = this.intentMat.opacity > 0.02;
    }

    // Prey keeps its own colour (players are recognised by colour) and flashes blue briefly.
    const blink = prey && Math.floor(elapsed * 4) % 3 === 2;
    this.skin.color.copy(this.baseColor).lerp(this.vulnerableColor, blink ? 0.6 : 0);
    this.skin.emissive.copy(this.skin.color);
    this.skin.emissiveIntensity = powered ? 0.55 : 0.22;
    if (this.youRing) this.youRing.rotation.z = elapsed * 0.8;
  }

  dispose(): void {
    for (const g of this.geometries) g.dispose();
    this.skin.dispose();
    this.auraMat.dispose();
    if (this.youRing) (this.youRing.material as THREE.Material).dispose();
    this.intentMat?.dispose();
    this.label.element.remove();
    this.root.removeFromParent();
  }
}

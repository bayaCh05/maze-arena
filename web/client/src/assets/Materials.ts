import * as THREE from 'three';

/** Shared materials and procedural textures. One instance each; disposed with the app. */
export class MaterialLibrary {
  readonly wall = new THREE.MeshStandardMaterial({ color: '#0d1233', roughness: 0.5, metalness: 0.3 });
  readonly wallTop = new THREE.MeshStandardMaterial({ color: '#111840', roughness: 0.35, metalness: 0.4, emissive: '#0a1450', emissiveIntensity: 0.35 });
  readonly neon = new THREE.MeshStandardMaterial({
    color: '#1a47ff',
    emissive: '#2160ff',
    emissiveIntensity: 1.2,
    roughness: 0.4,
  });
  readonly pellet = new THREE.MeshStandardMaterial({
    color: '#fff3d6',
    emissive: '#ffe2a3',
    emissiveIntensity: 1.5,
    roughness: 0.3,
  });
  readonly powerCore = new THREE.MeshStandardMaterial({
    color: '#ffffff',
    emissive: '#ff7ae6',
    emissiveIntensity: 3.2,
    roughness: 0.2,
  });
  readonly powerRing = new THREE.MeshStandardMaterial({
    color: '#ffd1f6',
    emissive: '#ff9bf0',
    emissiveIntensity: 1.8,
    roughness: 0.25,
    metalness: 0.4,
  });
  readonly mouth = new THREE.MeshStandardMaterial({ color: '#1b0510', roughness: 0.9, side: THREE.DoubleSide });
  readonly eye = new THREE.MeshStandardMaterial({ color: '#0b0d1c', roughness: 0.15, metalness: 0.2 });
  readonly eyeShine = new THREE.MeshBasicMaterial({ color: '#ffffff' });
  readonly contactShadow: THREE.MeshBasicMaterial;
  readonly floorTexture: THREE.CanvasTexture;
  readonly groundTexture: THREE.CanvasTexture;

  constructor(maxAnisotropy: number) {
    this.contactShadow = new THREE.MeshBasicMaterial({
      map: radialTexture('rgba(0,0,0,0.75)', 'rgba(0,0,0,0)'),
      transparent: true,
      depthWrite: false,
    });
    this.floorTexture = floorTileTexture(maxAnisotropy);
    this.groundTexture = groundGridTexture(maxAnisotropy);
  }

  dispose(): void {
    for (const value of Object.values(this)) {
      if (value instanceof THREE.Material) {
        (value as THREE.MeshBasicMaterial).map?.dispose();
        value.dispose();
      } else if (value instanceof THREE.Texture) {
        value.dispose();
      }
    }
  }
}

function radialTexture(inner: string, outer: string): THREE.CanvasTexture {
  const c = document.createElement('canvas');
  c.width = c.height = 128;
  const g = c.getContext('2d')!;
  const grad = g.createRadialGradient(64, 64, 4, 64, 64, 64);
  grad.addColorStop(0, inner);
  grad.addColorStop(1, outer);
  g.fillStyle = grad;
  g.fillRect(0, 0, 128, 128);
  const tex = new THREE.CanvasTexture(c);
  tex.colorSpace = THREE.SRGBColorSpace;
  return tex;
}

/** One maze cell: a dark floor tile with a beveled edge and a faint centre mark. Repeats per cell. */
function floorTileTexture(maxAnisotropy: number): THREE.CanvasTexture {
  const c = document.createElement('canvas');
  c.width = c.height = 128;
  const g = c.getContext('2d')!;
  g.fillStyle = '#060918';
  g.fillRect(0, 0, 128, 128);
  g.fillStyle = '#0b1030';
  roundRect(g, 5, 5, 118, 118, 14);
  g.fill();
  g.strokeStyle = 'rgba(80,110,255,0.18)';
  g.lineWidth = 2;
  roundRect(g, 5, 5, 118, 118, 14);
  g.stroke();
  g.strokeStyle = 'rgba(120,150,255,0.10)';
  g.lineWidth = 1.5;
  g.beginPath();
  g.moveTo(54, 64);
  g.lineTo(74, 64);
  g.moveTo(64, 54);
  g.lineTo(64, 74);
  g.stroke();
  const tex = new THREE.CanvasTexture(c);
  tex.colorSpace = THREE.SRGBColorSpace;
  tex.wrapS = tex.wrapT = THREE.RepeatWrapping;
  tex.anisotropy = maxAnisotropy;
  return tex;
}

/** The world around the maze: a faint grid that fades out, so the arena isn't floating in a void. */
function groundGridTexture(maxAnisotropy: number): THREE.CanvasTexture {
  const c = document.createElement('canvas');
  c.width = c.height = 64;
  const g = c.getContext('2d')!;
  g.fillStyle = '#04060f';
  g.fillRect(0, 0, 64, 64);
  g.strokeStyle = 'rgba(70,95,220,0.22)';
  g.lineWidth = 1;
  g.strokeRect(0.5, 0.5, 63, 63);
  const tex = new THREE.CanvasTexture(c);
  tex.colorSpace = THREE.SRGBColorSpace;
  tex.wrapS = tex.wrapT = THREE.RepeatWrapping;
  tex.anisotropy = maxAnisotropy;
  return tex;
}

export function roundRect(g: CanvasRenderingContext2D, x: number, y: number, w: number, h: number, r: number): void {
  g.beginPath();
  g.moveTo(x + r, y);
  g.arcTo(x + w, y, x + w, y + h, r);
  g.arcTo(x + w, y + h, x, y + h, r);
  g.arcTo(x, y + h, x, y, r);
  g.arcTo(x, y, x + w, y, r);
  g.closePath();
}

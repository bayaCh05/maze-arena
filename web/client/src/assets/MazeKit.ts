import * as THREE from 'three';
import { RoundedBoxGeometry } from 'three/addons/geometries/RoundedBoxGeometry.js';
import type { Cell } from '../net/protocol';
import { PLAYER_COLORS } from '../net/protocol';
import type { MaterialLibrary } from './Materials';

const WALL_H = 0.62;
const SPAWN_COLORS = [PLAYER_COLORS.yellow, PLAYER_COLORS.cyan, PLAYER_COLORS.magenta];

/** Grid cell -> world position (x right, z down the screen), maze centred on the origin. */
export class Grid {
  constructor(
    readonly width: number,
    readonly height: number,
  ) {}

  toWorld(x: number, y: number, out = new THREE.Vector3()): THREE.Vector3 {
    return out.set(x - this.width / 2 + 0.5, 0, y - this.height / 2 + 0.5);
  }
}

/**
 * The static maze built from GAME_START's rows ('#' wall, '1'-'3' spawn pads): instanced
 * beveled wall blocks, neon trim only on edges that face a corridor, tiled floor, spawn pads,
 * and the pellet / power-pellet sets that STATE updates every tick.
 */
export class MazeKit {
  readonly root = new THREE.Group();
  readonly grid: Grid;
  private readonly pellets: THREE.InstancedMesh;
  private readonly pelletIndex = new Map<string, number>();
  private readonly power: { cell: string; group: THREE.Group; core: THREE.Mesh; ring: THREE.Mesh }[] = [];
  private readonly geometries: THREE.BufferGeometry[] = [];
  private readonly ownedMaterials: THREE.Material[] = [];
  private readonly hidden = new THREE.Matrix4().makeScale(0, 0, 0);
  private readonly tmp = new THREE.Object3D();
  private shownPellets = new Set<string>();
  totalPellets = 0;

  constructor(
    readonly rows: string[],
    private readonly mats: MaterialLibrary,
  ) {
    this.grid = new Grid(rows[0].length, rows.length);
    this.root.name = 'mazeKit';
    this.buildFloor();
    this.buildWalls();
    this.pellets = this.buildPellets();
    this.buildPowerPellets();
  }

  /** Show exactly the pellets the server says are left. Returns the cells eaten since last call. */
  setPellets(pellets: Cell[], powerPellets: Cell[]): { eaten: string[]; powerEaten: string[] } {
    const next = new Set(pellets.map(([x, y]) => `${x},${y}`));
    const eaten: string[] = [];
    for (const [key, i] of this.pelletIndex) {
      const visible = next.has(key);
      if (!visible && this.shownPellets.has(key)) eaten.push(key);
      if (visible) {
        const [x, y] = key.split(',').map(Number);
        this.grid.toWorld(x, y, this.tmp.position);
        this.tmp.position.y = 0.32;
        this.tmp.scale.setScalar(1);
        this.tmp.updateMatrix();
        this.pellets.setMatrixAt(i, this.tmp.matrix);
      } else {
        this.pellets.setMatrixAt(i, this.hidden);
      }
    }
    this.pellets.instanceMatrix.needsUpdate = true;
    this.shownPellets = next;

    const powerNext = new Set(powerPellets.map(([x, y]) => `${x},${y}`));
    const powerEaten: string[] = [];
    for (const p of this.power) {
      if (p.group.visible && !powerNext.has(p.cell)) powerEaten.push(p.cell);
      p.group.visible = powerNext.has(p.cell);
    }
    return { eaten, powerEaten };
  }

  update(elapsed: number): void {
    this.mats.pellet.emissiveIntensity = 1.35 + Math.sin(elapsed * 3) * 0.2;
    for (const [i, p] of this.power.entries()) {
      const pulse = 1 + Math.sin(elapsed * 5 + i) * 0.14;
      p.core.scale.setScalar(pulse);
      p.core.rotation.y = elapsed * 1.6;
      p.ring.rotation.z = elapsed * 2.2 + i;
      p.group.position.y = 0.36 + Math.sin(elapsed * 2.4 + i) * 0.05;
    }
  }

  private buildFloor(): void {
    const { width, height } = this.grid;
    const floorGeo = new THREE.PlaneGeometry(width, height);
    this.geometries.push(floorGeo);
    const floorTex = this.mats.floorTexture.clone();
    floorTex.repeat.set(width, height);
    floorTex.needsUpdate = true;
    const floorMat = new THREE.MeshStandardMaterial({ map: floorTex, roughness: 0.82, metalness: 0.08 });
    this.ownedMaterials.push(floorMat);
    const floor = new THREE.Mesh(floorGeo, floorMat);
    floor.name = 'mazeFloor';
    floor.rotation.x = -Math.PI / 2;
    floor.receiveShadow = true;
    this.root.add(floor);

    const groundGeo = new THREE.PlaneGeometry(120, 120);
    this.geometries.push(groundGeo);
    const groundTex = this.mats.groundTexture.clone();
    groundTex.repeat.set(120, 120);
    groundTex.needsUpdate = true;
    const groundMat = new THREE.MeshStandardMaterial({ map: groundTex, roughness: 1, metalness: 0 });
    this.ownedMaterials.push(groundMat);
    const ground = new THREE.Mesh(groundGeo, groundMat);
    ground.name = 'outerGround';
    ground.rotation.x = -Math.PI / 2;
    ground.position.y = -0.02;
    ground.receiveShadow = true;
    this.root.add(ground);

    // Spawn pads: a coloured ring per start cell, in the colour of the player who starts there.
    const padGeo = new THREE.RingGeometry(0.28, 0.4, 40);
    this.geometries.push(padGeo);
    this.rows.forEach((row, y) =>
      [...row].forEach((ch, x) => {
        const n = '123'.indexOf(ch);
        if (n < 0) return;
        const mat = new THREE.MeshBasicMaterial({ color: SPAWN_COLORS[n], transparent: true, opacity: 0.55 });
        this.ownedMaterials.push(mat);
        const pad = new THREE.Mesh(padGeo, mat);
        pad.name = `spawnPad${n + 1}`;
        pad.rotation.x = -Math.PI / 2;
        this.grid.toWorld(x, y, pad.position).y = 0.012;
        this.root.add(pad);
      }),
    );
  }

  private isWall(x: number, y: number): boolean {
    return this.rows[y]?.[x] === '#';
  }

  private buildWalls(): void {
    const cells: [number, number][] = [];
    this.rows.forEach((row, y) => [...row].forEach((ch, x) => ch === '#' && cells.push([x, y])));

    const blockGeo = new RoundedBoxGeometry(0.98, WALL_H, 0.98, 2, 0.09);
    const capGeo = new RoundedBoxGeometry(0.8, 0.05, 0.8, 1, 0.02);
    this.geometries.push(blockGeo, capGeo);
    const blocks = new THREE.InstancedMesh(blockGeo, this.mats.wall, cells.length);
    const caps = new THREE.InstancedMesh(capGeo, this.mats.wallTop, cells.length);
    blocks.name = 'wallBlocks';
    caps.name = 'wallCaps';
    blocks.castShadow = blocks.receiveShadow = true;
    cells.forEach(([x, y], i) => {
      this.grid.toWorld(x, y, this.tmp.position);
      this.tmp.position.y = WALL_H / 2;
      this.tmp.scale.setScalar(1);
      this.tmp.rotation.set(0, 0, 0);
      this.tmp.updateMatrix();
      blocks.setMatrixAt(i, this.tmp.matrix);
      this.tmp.position.y = WALL_H + 0.01;
      this.tmp.updateMatrix();
      caps.setMatrixAt(i, this.tmp.matrix);
    });
    this.root.add(blocks, caps);

    // Neon trim along every wall edge that borders a corridor: outlines the playable paths.
    const edges: { x: number; y: number; dx: number; dy: number }[] = [];
    for (const [x, y] of cells) {
      for (const [dx, dy] of [[1, 0], [-1, 0], [0, 1], [0, -1]] as const) {
        const nx = x + dx;
        const ny = y + dy;
        if (ny >= 0 && ny < this.rows.length && nx >= 0 && nx < this.rows[0].length && !this.isWall(nx, ny)) {
          edges.push({ x, y, dx, dy });
        }
      }
    }
    const trimGeo = new THREE.BoxGeometry(0.96, 0.05, 0.05);
    this.geometries.push(trimGeo);
    const trim = new THREE.InstancedMesh(trimGeo, this.mats.neon, edges.length);
    trim.name = 'neonTrim';
    edges.forEach(({ x, y, dx, dy }, i) => {
      this.grid.toWorld(x, y, this.tmp.position);
      this.tmp.position.x += dx * 0.47;
      this.tmp.position.z += dy * 0.47;
      this.tmp.position.y = WALL_H - 0.02;
      this.tmp.rotation.set(0, dx !== 0 ? Math.PI / 2 : 0, 0);
      this.tmp.updateMatrix();
      trim.setMatrixAt(i, this.tmp.matrix);
    });
    this.root.add(trim);
  }

  private buildPellets(): THREE.InstancedMesh {
    const cells: string[] = [];
    this.rows.forEach((row, y) => [...row].forEach((ch, x) => ch === '.' && cells.push(`${x},${y}`)));
    this.totalPellets = cells.length;
    const geo = new THREE.IcosahedronGeometry(0.085, 1);
    this.geometries.push(geo);
    const mesh = new THREE.InstancedMesh(geo, this.mats.pellet, cells.length);
    mesh.name = 'pellets';
    cells.forEach((key, i) => this.pelletIndex.set(key, i));
    this.root.add(mesh);
    const all = cells.map((k) => k.split(',').map(Number) as Cell);
    const power: Cell[] = [];
    this.rows.forEach((row, y) => [...row].forEach((ch, x) => ch === 'o' && power.push([x, y])));
    this.shownPellets = new Set();
    // Fill the instance matrices once so a maze is complete even before the first STATE.
    queueMicrotask(() => this.setPellets(all, power));
    return mesh;
  }

  private buildPowerPellets(): void {
    const coreGeo = new THREE.OctahedronGeometry(0.17, 0);
    const ringGeo = new THREE.TorusGeometry(0.3, 0.022, 8, 40);
    this.geometries.push(coreGeo, ringGeo);
    this.rows.forEach((row, y) =>
      [...row].forEach((ch, x) => {
        if (ch !== 'o') return;
        const group = new THREE.Group();
        group.name = 'powerPellet';
        const core = new THREE.Mesh(coreGeo, this.mats.powerCore);
        core.name = 'powerCore';
        const ring = new THREE.Mesh(ringGeo, this.mats.powerRing);
        ring.name = 'powerRing';
        ring.rotation.x = Math.PI / 2.6;
        group.add(core, ring);
        this.grid.toWorld(x, y, group.position).y = 0.36;
        this.root.add(group);
        this.power.push({ cell: `${x},${y}`, group, core, ring });
      }),
    );
  }

  dispose(): void {
    for (const g of this.geometries) g.dispose();
    for (const m of this.ownedMaterials) {
      (m as THREE.MeshStandardMaterial).map?.dispose();
      m.dispose();
    }
    this.root.removeFromParent();
  }
}

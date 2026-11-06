import './styles.css';
import { App } from './game/App';

const canvas = document.querySelector<HTMLCanvasElement>('#game-canvas');
if (!canvas) throw new Error('Missing #game-canvas element.');

const app = new App(canvas);
app.start();

if (import.meta.hot) {
  import.meta.hot.dispose(() => app.dispose());
}

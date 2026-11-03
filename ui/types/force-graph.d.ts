/* No @types package exists for react-force-graph-3d: local shim covering
   exactly the props Tottie uses. If the lib's API drifts, tsc fails here. */
declare module "react-force-graph-3d" {
  import { Component } from "react";
  export interface GraphNode {
    id: string;
    label?: string;
    color?: string;
    val?: number;
    [key: string]: unknown;
  }
  export interface GraphLink {
    source: string | GraphNode;
    target: string | GraphNode;
    color?: string;
    [key: string]: unknown;
  }
  export interface ForceGraph3DProps {
    graphData: { nodes: GraphNode[]; links: GraphLink[] };
    nodeLabel?: string | ((n: GraphNode) => string);
    nodeColor?: string | ((n: GraphNode) => string);
    nodeVal?: string | ((n: GraphNode) => number);
    linkColor?: string | ((l: GraphLink) => string);
    linkLabel?: string | ((l: GraphLink) => string);
    linkWidth?: number | ((l: GraphLink) => number);
    linkDirectionalParticles?: number | ((l: GraphLink) => number);
    linkDirectionalParticleSpeed?: number;
    linkDirectionalParticleColor?: string | ((l: GraphLink) => string);
    nodeOpacity?: number;
    linkOpacity?: number;
    backgroundColor?: string;
    showNavInfo?: boolean;
    enableNodeDrag?: boolean;
    onNodeClick?: (n: GraphNode) => void;
    cooldownTime?: number;
  }
  export interface Coords {
    x: number;
    y: number;
    z: number;
  }
  export default class ForceGraph3D extends Component<ForceGraph3DProps> {
    // Imperative camera API the kapsule runtime exposes via ref
    // (useImperativeHandle). Declared here so Tottie can fly to newborns.
    zoomToFit(
      durationMs?: number,
      padding?: number,
      nodeFilter?: (node: GraphNode) => boolean
    ): void;
    cameraPosition(
      position: Partial<Coords>,
      lookAt?: Coords,
      transitionMs?: number
    ): void;
    // Re-runs the object digest (colors/sizes) WITHOUT touching the sim.
    // The per-frame animation path: mutate node objects, then refresh().
    refresh(): void;
  }
}

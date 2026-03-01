import React, { useRef } from 'react';
import { useLoader } from '@react-three/fiber';
import { STLLoader } from 'three/examples/jsm/loaders/STLLoader';
import { Center } from '@react-three/drei';

export default function STLModel({ url, color = "#0057ff", position = [0, 0, 0], scale = 1 }) {
    const geometry = useLoader(STLLoader, url);

    return (
        <Center top>
            <mesh
                position={position}
                scale={scale}
                onUpdate={(self) => {
                    self.geometry.computeVertexNormals();
                }}
            >
                <primitive object={geometry} attach="geometry" />
                <meshStandardMaterial
                    color={color}
                    metalness={0.6}
                    roughness={0.4}
                />
            </mesh>
        </Center>
    );
}

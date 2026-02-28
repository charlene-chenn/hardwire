import React from 'react';

const LEDGrid = () => {
    // Create a 12x12 grid of interaction points
    const points = Array.from({ length: 144 }, (_, i) => i);

    return (
        <div className="led-container floating">
            <div className="led-interaction-layer">
                {points.map((p) => (
                    <div key={p} className="led-point" />
                ))}
            </div>
            <img
                src="/led-grid.png"
                alt="LED Grid"
                className="led-image"
            />
        </div>
    );
};

export default LEDGrid;

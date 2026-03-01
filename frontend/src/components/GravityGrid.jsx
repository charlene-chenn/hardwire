import React, { useEffect, useRef } from 'react';

const GravityGrid = () => {
    const canvasRef = useRef(null);
    const mouseRef = useRef({ x: -1000, y: -1000 });
    const pointsRef = useRef([]);

    useEffect(() => {
        const canvas = canvasRef.current;
        const ctx = canvas.getContext('2d');
        let animationFrameId;
        const img = new Image();
        img.src = '/led-grid.png';

        const resize = () => {
            canvas.width = window.innerWidth;
            canvas.height = window.innerHeight;
            initPoints();
        };

        const initPoints = () => {
            if (!img.complete) return;

            // Create temporary canvas to scan image pixels
            const tempCanvas = document.createElement('canvas');
            const tempCtx = tempCanvas.getContext('2d');
            tempCanvas.width = img.width;
            tempCanvas.height = img.height;
            tempCtx.drawImage(img, 0, 0);

            const imageData = tempCtx.getImageData(0, 0, img.width, img.height).data;
            const points = [];
            const step = 8; // Scan every 8 pixels to find LED centers

            for (let y = 0; y < img.height; y += step) {
                for (let x = 0; x < img.width; x += step) {
                    const index = (y * img.width + x) * 4;
                    const r = imageData[index];
                    const g = imageData[index + 1];
                    const b = imageData[index + 2];

                    // Look for bright spots (LEDs)
                    if (r > 100 || g > 100 || b > 100) {
                        // Map image coordinates to screen coordinates
                        const screenX = (x / img.width) * canvas.width;
                        const screenY = (y / img.height) * canvas.height;

                        points.push({
                            originX: screenX,
                            originY: screenY,
                            x: screenX,
                            y: screenY,
                            vx: 0,
                            vy: 0,
                        });
                    }
                }
            }
            pointsRef.current = points;
        };

        const render = () => {
            if (!img.complete) {
                animationFrameId = requestAnimationFrame(render);
                return;
            }

            if (pointsRef.current.length === 0) {
                initPoints();
            }

            ctx.clearRect(0, 0, canvas.width, canvas.height);

            // Draw LED grid image as background with low opacity
            ctx.globalAlpha = 0.2;
            ctx.drawImage(img, 0, 0, canvas.width, canvas.height);

            const points = pointsRef.current;
            const mouse = mouseRef.current;
            const maxDist = 200;
            const friction = 0.9;
            const spring = 0.05;

            for (let p of points) {
                const dx = mouse.x - p.x;
                const dy = mouse.y - p.y;
                const dist = Math.sqrt(dx * dx + dy * dy);

                if (dist < maxDist) {
                    const angle = Math.atan2(dy, dx);
                    const force = (maxDist - dist) / maxDist;
                    p.vx -= Math.cos(angle) * force * 5;
                    p.vy -= Math.sin(angle) * force * 5;
                }

                p.vx += (p.originX - p.x) * spring;
                p.vy += (p.originY - p.y) * spring;
                p.vx *= friction;
                p.vy *= friction;
                p.x += p.vx;
                p.y += p.vy;

                const intensity = Math.max(0.3, 1 - dist / maxDist);
                ctx.globalAlpha = intensity;
                ctx.fillStyle = dist < maxDist ? '#00f2ff' : '#00a2ff';

                ctx.beginPath();
                ctx.arc(p.x, p.y, 3, 0, Math.PI * 2);
                ctx.fill();

                if (dist < maxDist) {
                    ctx.shadowBlur = 35 * intensity;
                    ctx.shadowColor = '#00f2ff';
                } else {
                    ctx.shadowBlur = 5 * intensity;
                    ctx.shadowColor = '#00a2ff';
                }
            }

            animationFrameId = requestAnimationFrame(render);
        };

        img.onload = () => {
            resize();
        };

        window.addEventListener('resize', resize);
        const handleMouseMove = (e) => {
            mouseRef.current = { x: e.clientX, y: e.clientY };
        };
        window.addEventListener('mousemove', handleMouseMove);

        resize();
        render();

        return () => {
            window.removeEventListener('resize', resize);
            window.removeEventListener('mousemove', handleMouseMove);
            cancelAnimationFrame(animationFrameId);
        };
    }, []);

    return (
        <canvas
            ref={canvasRef}
            className="gravity-canvas"
            style={{
                position: 'fixed',
                top: 0,
                left: 0,
                width: '100vw',
                height: '100vh',
                zIndex: -1,
                pointerEvents: 'none',
                background: 'transparent'
            }}
        />
    );
};

export default GravityGrid;

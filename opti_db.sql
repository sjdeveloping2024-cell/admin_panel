-- Create the database
CREATE DATABASE IF NOT EXISTS opti_db;
USE opti_db;

-- Employees Table
CREATE TABLE IF NOT EXISTS opti (
    id_employee INT PRIMARY KEY,  -- remove AUTO_INCREMENT
    name VARCHAR(100) NOT NULL,
    age INT,
    sex ENUM('Male','Female') NOT NULL,
    email VARCHAR(100),
    number VARCHAR(20),
    rfid VARCHAR(50) UNIQUE,
    password VARCHAR(255) DEFAULT NULL
);

-- Attendance / Salary Records Table
CREATE TABLE IF NOT EXISTS opti_rec (
    id INT AUTO_INCREMENT PRIMARY KEY,
    id_employee INT NOT NULL,
    time_in DATETIME,
    time_out DATETIME,
    duration INT DEFAULT 0,
    salary DECIMAL(10,2) DEFAULT 0,
    FOREIGN KEY (id_employee) REFERENCES opti(id_employee) ON DELETE CASCADE
);
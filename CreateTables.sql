-- Drop tables if they already exist (so reruns don’t fail)
DROP TABLE IF EXISTS minor;
DROP TABLE IF EXISTS major;
DROP TABLE IF EXISTS register;
DROP TABLE IF EXISTS courses;
DROP TABLE IF EXISTS degrees;
DROP TABLE IF EXISTS departments;
DROP TABLE IF EXISTS students;

-- Students table
CREATE TABLE students (
    sid INT NOT NULL,
    ssn INT NOT NULL,
    name VARCHAR(20),
    gender VARCHAR(1),
    dob VARCHAR(10),
    c_addr VARCHAR(20),
    c_phone VARCHAR(20),
    p_addr VARCHAR(20),
    p_phone VARCHAR(20),
    PRIMARY KEY (ssn),       -- primary key = ssn
    UNIQUE (sid)             -- candidate key = sid (must be unique for FKs)
);

-- Departments table
CREATE TABLE departments (
    dcode INT NOT NULL,
    dname VARCHAR(50),
    phone VARCHAR(10),
    college VARCHAR(20),
    PRIMARY KEY (dcode),
    UNIQUE (dname)
);

-- Degrees table
CREATE TABLE degrees (
    dgname VARCHAR(50) NOT NULL,
    level VARCHAR(5) NOT NULL,
    department_code INT,
    PRIMARY KEY (dgname, level),
    FOREIGN KEY (department_code) REFERENCES departments(dcode)
);

-- Courses table
CREATE TABLE courses (
    cnumber INT NOT NULL,
    cname VARCHAR(50),
    description VARCHAR(50),
    credithours INT,
    level VARCHAR(20),
    department_code INT,
    PRIMARY KEY (cnumber),
    FOREIGN KEY (department_code) REFERENCES departments(dcode)
);

-- Register table
CREATE TABLE register (
    sid INT NOT NULL,
    course_number INT NOT NULL,
    regtime VARCHAR(20),
    grade INT,
    PRIMARY KEY (sid, course_number),
    FOREIGN KEY (sid) REFERENCES students(sid),
    FOREIGN KEY (course_number) REFERENCES courses(cnumber)
);

-- Major table
CREATE TABLE major (
    sid INT NOT NULL,
    name VARCHAR(50) NOT NULL,
    level VARCHAR(5) NOT NULL,
    PRIMARY KEY (sid, name, level),
    FOREIGN KEY (sid) REFERENCES students(sid),
    FOREIGN KEY (name, level) REFERENCES degrees(dgname, level)
);

-- Minor table
CREATE TABLE minor (
    sid INT NOT NULL,
    name VARCHAR(50) NOT NULL,
    level VARCHAR(5) NOT NULL,
    PRIMARY KEY (sid, name, level),
    FOREIGN KEY (sid) REFERENCES students(sid),
    FOREIGN KEY (name, level) REFERENCES degrees(dgname, level)
);
